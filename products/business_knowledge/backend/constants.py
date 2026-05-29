"""
Constants and tunables for business_knowledge.
"""

# Per-team caps. Enforced in the create endpoint, not at the DB layer — easier
# to relax for a single paying customer without a migration.
MAX_SOURCES_PER_TEAM = 500
MAX_CHUNKS_PER_TEAM = 100_000
# 1 MB of raw text. Above this Stage 1 refuses the create; for longer docs the
# customer is expected to split them or wait for Stage 2/3.
MAX_TEXT_SIZE_BYTES = 1_000_000

# Chunker tunables. Kept here (not in logic.py) so the retrieval eval harness
# can import them without pulling Django.
CHUNK_TARGET_CHARS = 1200
CHUNK_HARD_MAX_CHARS = 1600

# --- Stage 2a: URL fetch tunables ---
# Hard cap on remote response bodies. Above this we abort mid-stream rather
# than ever materializing the full payload — protects memory and makes a
# zip-bomb attempt cheap to reject.
URL_MAX_BYTES = 10 * 1024 * 1024
# Connect + read timeouts (seconds). Short because fetch happens inline on
# the request thread; Stage 5 moves it to Temporal and can be generous.
URL_CONNECT_TIMEOUT = 5
URL_READ_TIMEOUT = 10
# Max redirect hops. We handle redirects manually so we can re-validate SSRF
# on every Location header.
URL_MAX_REDIRECTS = 5
# Self-identifying User-Agent — gives site operators something searchable
# and a contact point if we hammer their site by accident. URL_BOT_NAME is
# the short token site operators target in robots.txt; it MUST appear at the
# start of URL_USER_AGENT so urllib.robotparser's prefix match lines up.
URL_BOT_NAME = "PostHog-BusinessKnowledge"
URL_USER_AGENT = f"{URL_BOT_NAME}/1.0 (+https://posthog.com)"

# --- Stage 2b: crawl tunables ---
# Discover step cap — sitemap / same-origin BFS stops emitting after this
# many candidate URLs (BEFORE glob filtering). Purely defensive: a pathological
# sitemap.xml can list 100k URLs.
HARD_DISCOVER_CAP = 10_000
# Fetch step default cap. Settable per-source via `crawl_config.max_pages`,
# but users can never exceed MAX_URLS_PER_SOURCE. Deliberately low because
# Stage 2b is inline — every fetch blocks a request worker. Stage 5 moves
# this to Temporal and can raise the cap.
DEFAULT_MAX_PAGES = 50
MAX_URLS_PER_SOURCE = 500
# Default recursion depth for `same_origin` BFS.
DEFAULT_CRAWL_MAX_DEPTH = 2
CRAWL_HARD_MAX_DEPTH = 5
# Per-hostname concurrency during a single crawl — prevents us from
# hammering an origin. In-process (threading.Semaphore), not cross-worker;
# cross-worker rate limiting is Stage 5 Temporal work.
PER_HOST_CONCURRENCY = 2

# --- Stage 3: file upload tunables ---
# Hard cap on uploaded file size (compressed). Above this the serializer
# rejects immediately — the file never hits the parser.
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
# Decompressed size cap for ZIP-based formats (DOCX, XLSX, ODT). A 1 MB
# docx can decompress to 10 GB — 100 MB is generous for any legitimate
# knowledge document while keeping per-request memory bounded.
MAX_FILE_DECOMPRESSED_BYTES = 100 * 1024 * 1024
