"""
International Tax Special Agent — run_agent.py
Fetches international taxation news, classifies with Gemini 2.5 Flash,
maintains 7-day archive, generates Signal of the Day, tracks countries
and treaties, renders int_tax_report.html for GitHub Pages.
"""
 
import os, sys, json, time, hashlib, logging, calendar
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
 
import feedparser, requests, pytz
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
import google.generativeai as genai
from jinja2 import Environment, FileSystemLoader
 
HELSINKI = pytz.timezone("Europe/Helsinki")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("int-tax-agent")
 
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
LOOKBACK_HOURS  = 48
ARCHIVE_DAYS    = 7
MAX_ITEMS       = 40
REQUEST_TIMEOUT = 15
 
REPO_ROOT    = Path(__file__).parent.parent
ARCHIVE_FILE = REPO_ROOT / "archive.json"
 
# ── Publisher map ─────────────────────────────────────────────────────────────
PUBLISHER_MAP = {
    "bloombergtax.com":        "Bloomberg Tax",
    "bloomberg.com":           "Bloomberg Tax",
    "reuters.com":             "Reuters",
    "ft.com":                  "Financial Times",
    "law360.com":              "Law360",
    "taxnotes.com":            "Tax Notes",
    "mnetax.com":              "MNE Tax",
    "internationaltaxreview.com": "Int'l Tax Review",
    "taxfoundation.org":       "Tax Foundation",
    "taxjustice.net":          "Tax Justice Network",
    "oecd.org":                "OECD",
    "taxguru.in":              "TaxGuru India",
    "ibfd.org":                "IBFD",
    "pwc.com":                 "PwC Tax",
    "deloitte.com":            "Deloitte Tax",
    "ey.com":                  "EY Tax",
    "kpmg.com":                "KPMG Tax",
    "taxobservatory.eu":       "EU Tax Observatory",
    "eur-lex.europa.eu":       "EUR-Lex",
    "curia.europa.eu":         "CJEU",
    "ec.europa.eu":            "EU Commission",
    "consilium.europa.eu":     "EU Council",
    "europarl.europa.eu":      "EU Parliament",
    "un.org":                  "United Nations",
    "imf.org":                 "IMF",
    "worldbank.org":           "World Bank",
}
 
# ── Keywords ──────────────────────────────────────────────────────────────────
INT_TAX_KEYWORDS = [
    # Pillar Two — core focus
    "pillar two", "pillar 2", "GloBE", "UTPR", "STTR", "QDMTT", "IIR",
    "global minimum tax", "minimum tax", "top-up tax",
    "income inclusion rule", "undertaxed profits",
 
    # EU tax framework
    "CJEU", "Court of Justice", "EU tax", "European Court",
    "ATAD", "DAC6", "DAC7", "DAC8", "BEFIT", "UNSHELL",
    "state aid", "EU directive", "tax directive",
    "anti-tax avoidance", "hybrid mismatch",
 
    # Tax treaties
    "tax treaty", "double taxation", "tax convention",
    "tax agreement", "withholding tax treaty",
    "UN tax convention", "MLI", "multilateral instrument",
    "competent authority", "tax information exchange",
 
    # Digital economy
    "digital services tax", "DST", "digital tax",
    "digital economy taxation", "marketplace tax",
 
    # International framework
    "BEPS", "OECD", "base erosion", "profit shifting",
    "controlled foreign", "CFC", "CFC rules",
    "substance requirements", "economic substance",
    "beneficial ownership", "tax haven",
    "country-by-country", "CbCR",
    "international tax", "cross-border tax",
    "tax avoidance", "tax evasion",
    "advance pricing", "mutual agreement", "MAP",
]
 
# ── Lenses ────────────────────────────────────────────────────────────────────
LENSES = [
    "Pillar Two / GloBE",
    "CJEU & EU Court decisions",
    "EU Tax Directives",
    "Tax treaties & conventions",
    "Digital economy taxation",
    "State aid",
    "CFC & anti-avoidance",
    "Country guidance",
    "Tax transparency",
    "General international tax",
]
 
# ── Countries to track ────────────────────────────────────────────────────────
TRACKED_COUNTRIES = [
    "Ireland", "Netherlands", "Luxembourg", "Switzerland", "Belgium",
    "Germany", "France", "Italy", "Spain", "Sweden", "Denmark", "Finland",
    "United States", "United Kingdom", "Singapore", "Hong Kong",
    "Cayman Islands", "Bermuda", "Malta", "Cyprus",
    "India", "China", "Japan", "Australia", "Canada", "Brazil",
    "UAE", "Saudi Arabia",
]
 
# ── RSS Feeds ─────────────────────────────────────────────────────────────────
RSS_FEEDS = [
    # Google News — international tax queries
    {"name": "Google News — Pillar Two",
     "url": "https://news.google.com/rss/search?q=%22pillar+two%22+%22global+minimum+tax%22&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    {"name": "Google News — GloBE",
     "url": "https://news.google.com/rss/search?q=GloBE+UTPR+%22international+tax%22&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    {"name": "Google News — CJEU Tax",
     "url": "https://news.google.com/rss/search?q=CJEU+%22tax%22+ruling&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    {"name": "Google News — EU Tax Directive",
     "url": "https://news.google.com/rss/search?q=%22EU+tax%22+directive+OR+ATAD+OR+DAC&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    {"name": "Google News — Tax Treaty",
     "url": "https://news.google.com/rss/search?q=%22tax+treaty%22+OR+%22double+taxation%22&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    {"name": "Google News — Digital Tax",
     "url": "https://news.google.com/rss/search?q=%22digital+services+tax%22+OR+%22digital+tax%22&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    {"name": "Google News — OECD International Tax",
     "url": "https://news.google.com/rss/search?q=OECD+%22international+tax%22&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    {"name": "Google News — State Aid Tax",
     "url": "https://news.google.com/rss/search?q=%22state+aid%22+tax+EU&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    # Big Four — international tax alerts
    {"name": "Google News — KPMG Int Tax",
     "url": "https://news.google.com/rss/search?q=KPMG+%22international+tax%22+OR+%22pillar+two%22&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    {"name": "Google News — PwC Int Tax",
     "url": "https://news.google.com/rss/search?q=PwC+%22international+tax%22+OR+%22pillar+two%22&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    {"name": "Google News — Deloitte Int Tax",
     "url": "https://news.google.com/rss/search?q=Deloitte+%22international+tax%22+OR+%22GloBE%22&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    {"name": "Google News — EY Int Tax",
     "url": "https://news.google.com/rss/search?q=%22Ernst+Young%22+%22international+tax%22&hl=en-US&gl=US&ceid=US:en",
     "open": True},
    # Specialist feeds
    {"name": "Tax Foundation",
     "url": "https://taxfoundation.org/feed/", "open": True},
    {"name": "Tax Justice Network",
     "url": "https://taxjustice.net/feed/", "open": True},
    {"name": "EU Tax Observatory",
     "url": "https://www.taxobservatory.eu/feed/", "open": True},
    {"name": "MNE Tax",
     "url": "https://mnetax.com/feed", "open": True},
    # ── OECD direct feed ─────────────────────────────────────────────────────
    {"name": "OECD Tax",
     "url": "https://www.oecd.org/tax/rss.xml", "open": True},
]
 
# ── Helpers ───────────────────────────────────────────────────────────────────
def item_id(url): return hashlib.md5(url.encode()).hexdigest()[:12]
 
def parse_dt(entry):
    struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if struct:
        try: return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
        except: pass
    date_str = getattr(entry, "published", "") or getattr(entry, "updated", "")
    if date_str:
        try:
            dt = dateparser.parse(date_str)
            if dt: return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except: pass
    return None
 
def is_recent(entry):
    dt = parse_dt(entry)
    return True if dt is None else dt >= datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
 
def is_relevant(text):
    lower = text.lower()
    return any(kw.lower() in lower for kw in INT_TAX_KEYWORDS)
 
def hours_ago(pub_str):
    if not pub_str: return None
    try:
        dt = dateparser.parse(pub_str)
        if not dt: return None
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
        h = int(delta.total_seconds() // 3600)
        if h < 1: return "just now"
        if h < 24: return f"{h}h ago"
        return f"{h // 24}d ago"
    except: return None
 
def extract_publisher(title, url, feed_name, entry=None):
    if entry:
        src = getattr(entry, "source", None)
        if src:
            src_title = getattr(src, "title", "")
            if src_title and len(src_title) < 60: return src_title
    if " - " in title:
        suffix = title.rsplit(" - ", 1)[-1].strip()
        for domain, name in PUBLISHER_MAP.items():
            if domain in suffix.lower(): return name
        if 2 < len(suffix) < 50 and "." not in suffix and suffix[0].isupper():
            return suffix
    for domain, name in PUBLISHER_MAP.items():
        if domain in url.lower(): return name
    if feed_name.startswith("Google News — "):
        return feed_name.replace("Google News — ", "GN: ")
    return feed_name
 
def check_url_open(url):
    try:
        r = requests.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True,
                          headers={"User-Agent": "IntTax-Agent/1.0"})
        final = r.url.lower()
        if r.status_code in (401, 402, 403): return False
        if any(p in final for p in ["/subscribe", "/login", "/paywall"]): return False
        return r.status_code < 400
    except: return False
 
def extract_countries(text):
    found = []
    lower = text.lower()
    for country in TRACKED_COUNTRIES:
        if country.lower() in lower:
            found.append(country)
    return found[:3]
 
def detect_treaty(text):
    signals = ["new tax treaty", "signs tax treaty", "tax agreement signed",
                "renegotiated treaty", "new convention", "tax convention signed",
                "double taxation agreement", "new DTA", "DTA signed"]
    lower = text.lower()
    return any(s in lower for s in signals)
 
def detect_finnish_relevance(text):
    signals = [
        "finland", "finnish", "suomi", "suomen", "verohallinto",
        "kho", "finnish tax", "nordic", "scandinav",
        "helsinki", "finnish authorities", "vero",
    ]
    lower = text.lower()
    return any(s in lower for s in signals)
 
# ── Fetch ─────────────────────────────────────────────────────────────────────
def fetch_items():
    items = []
    for feed_cfg in RSS_FEEDS:
        try:
            log.info(f"Fetching: {feed_cfg['name']}")
            feed = feedparser.parse(feed_cfg["url"],
                                    request_headers={"User-Agent": "IntTax-Agent/1.0"})
            status = getattr(feed, "status", "?")
            n = len(feed.entries)
            log.info(f"  status={status} entries={n}")
            before = len(items)
            for entry in feed.entries:
                title   = getattr(entry, "title",   "").strip()
                summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
                link    = getattr(entry, "link",    "").strip()
                pub_str = getattr(entry, "published", "") or getattr(entry, "updated", "")
                if not title or not link: continue
                if not is_recent(entry): continue
                combined = f"{title} {summary}"
                if not is_relevant(combined): continue
                publisher = extract_publisher(title, link, feed_cfg["name"], entry)
                clean_title = title
                if " - " in title:
                    suffix = title.rsplit(" - ", 1)[-1].strip()
                    if "." in suffix or any(d in suffix.lower() for d in PUBLISHER_MAP):
                        clean_title = title.rsplit(" - ", 1)[0].strip()
                countries   = extract_countries(combined)
                is_treaty   = detect_treaty(combined)
                is_finnish  = detect_finnish_relevance(combined)
                items.append({
                    "id":        item_id(link),
                    "title":     clean_title,
                    "summary":   BeautifulSoup(summary, "lxml").get_text(" ", strip=True)[:600],
                    "url":       link,
                    "source":    publisher,
                    "pub":       pub_str,
                    "open":      feed_cfg["open"],
                    "countries":  countries,
                    "is_treaty":  is_treaty,
                    "is_finnish": is_finnish,
                })
            log.info(f"  -> {len(items)-before} relevant items")
        except Exception as e:
            log.warning(f"Feed failed {feed_cfg['name']}: {e}")
    log.info(f"Total fetched: {len(items)}")
    return items
 
def deduplicate(items):
    seen, out = set(), []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            out.append(item)
    return out
 
# ── Gemini classify ───────────────────────────────────────────────────────────
CLASSIFY_PROMPT = """You are a senior international tax lawyer and policy expert.
 
Enrich each item. Importance score determines page placement.
 
── IMPORTANCE SCORING ──────────────────────────────────────────────────────────
TIER 1 — importance 4 or 5 (shown prominently):
  5 = Landmark: CJEU Grand Chamber ruling, OECD final Pillar Two guidance,
      new EU Directive enacted, UN Tax Convention breakthrough, landmark state aid decision
  4 = Major: significant CJEU/national court ruling on international tax,
      new country Pillar Two legislation, new tax treaty signed,
      new digital services tax, major OECD consultation,
      EU Commission state aid investigation opened/closed
 
TIER 2 — importance 2 or 3:
  3 = Notable: policy consultation, country implementation update,
      noteworthy practitioner analysis, DAC/CbCR development
  2 = Update: minor guidance, procedural update, academic commentary
 
TIER 3 — importance 1 (archive only):
  1 = Background: general tax news tangentially mentioning international tax
 
── LENS (ONE of): {lenses} ─────────────────────────────────────────────────────
  "Pillar Two / GloBE"         → GloBE rules, UTPR, STTR, QDMTT, IIR, minimum tax
  "CJEU & EU Court decisions"  → ANY CJEU or EU court ruling on tax matters
  "EU Tax Directives"          → ATAD, DAC6/7/8, BEFIT, UNSHELL, new EU tax law
  "Tax treaties & conventions" → bilateral treaties, UN convention, MLI, DTA
  "Digital economy taxation"   → DSTs, platform taxation, digital nexus rules
  "State aid"                  → EU Commission decisions, CJEU state aid cases
  "CFC & anti-avoidance"       → CFC rules, hybrid mismatches, GAAR, SAAR
  "Country guidance"           → national implementation of international rules
  "Tax transparency"           → CbCR, DAC reporting, FATCA, info exchange
  "General international tax"  → catch-all only if nothing else fits
 
── OTHER FIELDS ────────────────────────────────────────────────────────────────
region: ONE of: Global, EU, US, APAC, Nordic, Other
country_focus: primary country this item is about (single country name or "Global")
ai_summary: 2 sentences with specific facts. State jurisdiction, case name, amount if known.
            Never write "this article discusses..." — be specific and analytical.
discard: true ONLY if completely unrelated to international taxation.
 
Return ONLY valid JSON:
{{"items":[{{"id":"...","lens":"...","region":"...","country_focus":"...","importance":3,"ai_summary":"...","discard":false}}]}}
 
Items:
{items_json}"""
 
def classify_with_gemini(items):
    if not GEMINI_API_KEY:
        log.error("GEMINI_API_KEY not set"); sys.exit(1)
    genai.configure(api_key=GEMINI_API_KEY)
    model    = genai.GenerativeModel("gemini-2.5-flash")
    enriched = []
    for i in range(0, len(items), 15):
        batch = items[i:i+15]
        batch_input = [{"id":it["id"],"title":it["title"],"summary":it["summary"]} for it in batch]
        prompt = CLASSIFY_PROMPT.format(
            lenses=", ".join(LENSES),
            items_json=json.dumps(batch_input, ensure_ascii=False, indent=2))
        try:
            log.info(f"Classifying batch {i//15+1} ({len(batch)} items)...")
            raw = None
            for attempt in range(3):
                try:
                    raw = model.generate_content(prompt).text.strip()
                    break
                except Exception as e:
                    if "429" in str(e) and attempt < 2:
                        wait = 35*(attempt+1)
                        log.warning(f"Quota hit, retrying in {wait}s...")
                        time.sleep(wait)
                    else: raise
            if raw is None: raise Exception("All retries failed")
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"): raw = raw[4:]
            classified = {it["id"]:it for it in json.loads(raw).get("items",[])}
            for item in batch:
                meta = classified.get(item["id"],{})
                if meta.get("discard"): continue
                item["lens"]          = meta.get("lens","General international tax")
                item["region"]        = meta.get("region","Global")
                item["country_focus"] = meta.get("country_focus","Global")
                item["importance"]    = int(meta.get("importance",2))
                item["ai_summary"]    = meta.get("ai_summary",item["summary"][:300])
                item["freshness"]     = hours_ago(item.get("pub",""))
                enriched.append(item)
            time.sleep(1.5)
        except Exception as e:
            log.warning(f"Gemini batch failed: {e}")
            for item in batch:
                item["lens"]          = "General international tax"
                item["region"]        = "Global"
                item["country_focus"] = "Global"
                item["importance"]    = 2
                item["ai_summary"]    = item["summary"][:300] or item["title"]
                item["freshness"]     = hours_ago(item.get("pub",""))
                enriched.append(item)
    return enriched
 
# ── Signal of the Day ─────────────────────────────────────────────────────────
SIGNAL_PROMPT = """You are a senior international tax partner at a global law firm in Paris.
 
Based on today's international tax news, identify the single most important development
for a multinational's global tax position and compliance obligations.
 
Return ONLY valid JSON:
{{"headline":"One punchy sentence max 12 words","body":"Two sentences of expert analysis. What does this mean for multinationals in practice?","lens":"one of: {lenses}","urgency":"high|medium|low","country_focus":"primary country or Global"}}
 
Today's items:
{items_json}"""
 
def get_signal_of_day(items):
    if not items:
        return {"headline":"Scanning international tax developments — no major signals today",
                "body":"All monitored sources are quiet. The Paris desk will update tomorrow.",
                "lens":"General international tax","urgency":"low","country_focus":"Global"}
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        top   = sorted(items, key=lambda x: -x.get("importance",0))[:10]
        payload = [{"title":it["title"],"source":it["source"],
                    "lens":it.get("lens",""),"importance":it.get("importance",2)}
                   for it in top]
        raw = model.generate_content(
            SIGNAL_PROMPT.format(lenses=", ".join(LENSES),
                                 items_json=json.dumps(payload, ensure_ascii=False, indent=2))
        ).text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        log.warning(f"Signal of the Day failed: {e}")
        return {"headline":"International tax intelligence gathered — see items below",
                "body":"Signal analysis unavailable. All items are classified below.",
                "lens":"General international tax","urgency":"low","country_focus":"Global"}
 
# ── Archive ───────────────────────────────────────────────────────────────────
def load_archive():
    if ARCHIVE_FILE.exists():
        try: return json.loads(ARCHIVE_FILE.read_text(encoding="utf-8"))
        except: pass
    return []
 
def save_archive(today_items, archive):
    today_date = datetime.now(HELSINKI).strftime("%Y-%m-%d")
    cutoff     = (datetime.now(timezone.utc)-timedelta(days=ARCHIVE_DAYS)).strftime("%Y-%m-%d")
    for item in today_items: item["archive_date"] = today_date
    existing_ids = {it["id"] for it in today_items}
    merged = list(today_items)
    for item in archive:
        if item["id"] not in existing_ids and item.get("archive_date","") >= cutoff:
            merged.append(item); existing_ids.add(item["id"])
    merged.sort(key=lambda x: x.get("archive_date",""), reverse=True)
    ARCHIVE_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Archive: {len(merged)} items saved")
    return merged
 
def build_archive_by_day(archive):
    by_day = defaultdict(list)
    for item in archive: by_day[item.get("archive_date","unknown")].append(item)
    return sorted(by_day.items(), reverse=True)
 
def build_sparklines(archive):
    today = datetime.now(HELSINKI).date()
    days  = [(today-timedelta(days=i)).isoformat() for i in range(6,-1,-1)]
    sparks = {lens:[0]*7 for lens in LENSES}
    for item in archive:
        d=item.get("archive_date",""); lens=item.get("lens","General international tax")
        if d in days and lens in sparks: sparks[lens][days.index(d)] += 1
    return sparks
 
def build_country_counts(items):
    counts = defaultdict(int)
    for item in items:
        for c in item.get("countries",[]):
            counts[c] += 1
        cf = item.get("country_focus","")
        if cf and cf != "Global" and cf in TRACKED_COUNTRIES:
            counts[cf] += 1
    return dict(sorted(counts.items(), key=lambda x:-x[1])[:10])
 
def get_treaty_alerts(items):
    return [it for it in items if it.get("is_treaty")]
 
def check_accessibility(items):
    log.info("Checking URL accessibility...")
    for item in items:
        item["accessible"] = check_url_open(item["url"]) if item.get("open",True) else False
    return items
 
# ── Render ────────────────────────────────────────────────────────────────────
def render_report(items, signal, archive, sparklines, country_counts):
    items.sort(key=lambda x: (-x.get("importance",0), x.get("source","")))
    main_items = [it for it in items if it.get("importance",1) >= 2][:MAX_ITEMS]
    by_lens = defaultdict(list)
    for item in main_items: by_lens[item.get("lens","General international tax")].append(item)
    lens_order = [l for l in LENSES if l in by_lens]
    high_importance_count = sum(1 for it in main_items if it.get("importance",0) >= 4)
    now_helsinki  = datetime.now(HELSINKI)
    archive_by_day = build_archive_by_day(archive)
    today = now_helsinki.date()
    day_labels = {}
    for d,_ in archive_by_day:
        try:
            dt = datetime.strptime(d,"%Y-%m-%d").date()
            diff = (today-dt).days
            if diff==0: day_labels[d]="Today"
            elif diff==1: day_labels[d]="Yesterday"
            else: day_labels[d]=dt.strftime("%A, %d %b")
        except: day_labels[d]=d
 
    env = Environment(loader=FileSystemLoader(REPO_ROOT/"templates"), autoescape=True)
    return env.get_template("report.html").render(
        generated_at          = now_helsinki.strftime("%A, %d %B %Y · %H:%M")+" "+now_helsinki.strftime("%Z"),
        generated_date        = now_helsinki.strftime("%Y-%m-%d"),
        total_items           = len(main_items),
        high_importance_count = high_importance_count,
        by_lens               = by_lens,
        lens_order            = lens_order,
        importance_labels     = {5:"Landmark",4:"Major",3:"Notable",2:"Update",1:"Background"},
        signal                = signal,
        archive_by_day        = archive_by_day,
        day_labels            = day_labels,
        sparklines            = sparklines,
        country_counts        = country_counts,
    )
 
# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("── International Tax Special Agent starting ──")
    raw_items     = deduplicate(fetch_items())
    log.info(f"Unique items: {len(raw_items)}")
    enriched      = classify_with_gemini(raw_items) if raw_items else []
    enriched      = check_accessibility(enriched)
    signal        = get_signal_of_day(enriched)
    archive       = load_archive()
    archive       = save_archive(enriched, archive)
    sparklines    = build_sparklines(archive)
    country_counts = build_country_counts(enriched)
    html = render_report(enriched, signal, archive, sparklines, country_counts)
    out  = REPO_ROOT/"int_tax_report.html"
    out.write_text(html, encoding="utf-8")
    log.info(f"Report written: {len(html):,} bytes")
 
if __name__ == "__main__":
    main()