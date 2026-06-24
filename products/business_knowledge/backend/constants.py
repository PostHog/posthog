"""
Constants and tunables for business_knowledge.
"""

import datetime

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
# Total bytes of page bodies the same-origin BFS may carry over to the fetch
# phase (so traversed pages aren't downloaded twice). Past the budget the
# fetch phase re-downloads — a bounded-memory tradeoff, not a correctness one.
PREFETCH_CACHE_MAX_BYTES = 64 * 1024 * 1024

# --- Stage 3: file upload tunables ---
# Hard cap on uploaded file size (compressed). Above this the serializer
# rejects immediately — the file never hits the parser.
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
# Decompressed size cap for ZIP-based formats (DOCX, XLSX, ODT). A 1 MB
# docx can decompress to 10 GB — 100 MB is generous for any legitimate
# knowledge document while keeping per-request memory bounded.
MAX_FILE_DECOMPRESSED_BYTES = 100 * 1024 * 1024

# --- Stage 5: safety classifier tunables ---
# The classifier is a security boundary: the span it inspects MUST equal the
# span that becomes searchable, otherwise an attacker can hide a prompt-
# injection payload past the inspected region and still have it indexed and
# surfaced to the agent. We therefore classify the WHOLE document in overlapping
# windows (a doc is UNSAFE if any window is) rather than only a leading prefix.
#
# Window size is a cost knob, not a security knob — every window is inspected
# regardless. Overlap guards against a payload straddling a window boundary.
CLASSIFY_WINDOW_CHARS = 100_000
CLASSIFY_WINDOW_OVERLAP_CHARS = 1_000
# Hard cap on how much of one document we will classify. Documents longer than
# this are failed CLOSED (left excluded from search) rather than partially
# inspected and waved through — never apply a partial-document verdict to the
# full, searchable document. Also bounds per-doc memory + LLM calls. Sized to
# the text-source cap (MAX_TEXT_SIZE_BYTES); larger crawled/file docs are rare
# and an operator can split them.
CLASSIFY_MAX_TOTAL_CHARS = 1_000_000
# How many coordinator passes may try to classify a single doc before we give
# up and leave it excluded. The classifier fails closed, so an unclassifiable
# doc stays `unknown` (never searchable); this only bounds the retry churn. At
# the hourly cadence this is ~5 hours of retries — enough to ride out a
# transient Gemini outage, bounded enough to not loop forever on poison content.
CLASSIFY_MAX_ATTEMPTS = 5

# --- Embedding pipeline tunables (hybrid retrieval) ---
# Embedding model used for both producing chunk vectors and (later) embedding
# search queries. MUST match a model_name in error_tracking's EMBEDDING_TABLES,
# and emit-model MUST equal query-model or cosineDistance compares across spaces.
BK_EMBEDDING_MODEL = "text-embedding-3-small-1536"
# `product` / `document_type` buckets in the shared `document_embeddings` table.
# One embedding row per chunk (document_id = chunk_id) so citations stay stable
# and the read path can re-join to Postgres chunks. Shared with the read path.
BK_EMBEDDING_PRODUCT = "business_knowledge"
BK_EMBEDDING_DOCUMENT_TYPE = "chunk"
BK_EMBEDDING_RENDERING = "plain"
# Per coordinator pass: how many SAFE documents we pull to emit embeddings for.
# Each pending doc loads its chunk content into memory to produce to Kafka, so
# this is the same memory knob as PENDING_CLASSIFICATION_SCAN_CAP. Kept small so
# the first post-deploy pass (which backfills every existing SAFE doc across all
# teams) drains over many hourly passes instead of blowing up one run.
PENDING_EMBEDDING_SCAN_CAP = 50
# Reconciliation: how many already-emitted SAFE docs to re-verify against
# ClickHouse per pass (oldest-emitted first), and the grace period a doc must
# have been emitted for before it's eligible. The grace window keeps us from
# re-checking docs whose vectors are simply still in flight through Kafka.
RECONCILE_EMBEDDING_SCAN_CAP = 50
RECONCILE_EMBEDDING_GRACE = datetime.timedelta(hours=2)
# Periodic TTL refresh. The shared document_embeddings table TTLs rows at
# `timestamp + 3 MONTH`, computed from the user-supplied `timestamp` we pass at
# emit time (NOT inserted_at). A SAFE doc embedded once and never re-emitted
# silently loses its vectors after ~3 months and falls back to FTS-only forever
# — the first-emission `embeddings_emitted_at IS NULL` guard means it's never
# re-emitted on its own. This window picks up docs whose last emission is older
# than ~2 months, comfortably under the 3-month TTL, so the re-emit lands a
# fresh live row before the old one expires.
#
# Both the TTL-refresh path and the first-emission path for OLD docs (created_at
# older than EMBEDDING_STABLE_TS_MAX_AGE) use timestamp=now() — the TTL is on
# `timestamp`, so emitting under an old created_at would land an expired or
# soon-to-expire row. Young docs still use the stable created_at for sort-key
# dedup. The fresh-timestamp row lands under today's partition; any prior row
# ages out under its own TTL. This is correctness-safe: the read path always
# re-joins to Postgres and dedups candidates by chunk_id, so a transient extra
# row can never double-count or surface stale content.
EMBEDDING_TTL_REFRESH_WINDOW = datetime.timedelta(days=60)
# The shared embeddings table TTLs rows at `timestamp + 3 MONTH` (see
# error_tracking's indexed_embedding.py — the table definition is the source of
# truth; this mirrors it for arithmetic).
BK_EMBEDDING_TABLE_TTL = datetime.timedelta(days=90)
# Max document age at first emit for which the stable created_at timestamp is
# safe. The invariant: the row must survive until the refresh cron re-emits at
# emitted_at + EMBEDDING_TTL_REFRESH_WINDOW, i.e. created_at + TTL must exceed
# that — so created_at can be at most TTL - REFRESH_WINDOW old. Older docs
# (incl. re-nulled in-place crawl docs, late-SAFE classifications, and backfill)
# must emit with now() or they'd lose vectors before the refresh cron fires.
EMBEDDING_STABLE_TS_MAX_AGE = BK_EMBEDDING_TABLE_TTL - EMBEDDING_TTL_REFRESH_WINDOW
# Per coordinator pass: how many aging SAFE docs to re-emit (oldest-emitted
# first). Same memory knob as the other embedding caps — each doc loads its
# chunk content to produce to Kafka. A large refresh wave drains over many
# hourly passes instead of blowing up a single run across all teams.
REEMIT_EMBEDDING_SCAN_CAP = 50

# --- Hybrid retrieval tunables (PR2 read path) ---
# cosineDistance threshold: vectors above this are discarded BEFORE re-joining
# Postgres. text-embedding-3-small typically returns 0.2–0.5 for related content
# and 0.7+ for unrelated. Start strict; loosen with data.
BK_SEMANTIC_DISTANCE_CUTOFF = 0.65
# Over-fetch factor: the safety re-join can discard top-k hits that point at
# now-UNSAFE/tombstoned/deleted chunks, so we pull k * OVERFETCH from CH and
# trim after re-join. 3x is generous; a lower factor would be fine once the
# pipeline stabilises.
BK_SEMANTIC_OVERFETCH = 3
# RRF fusion constant. Standard value from the original RRF paper (Cormack et
# al. 2009). Higher k flattens rank differences; lower k emphasises top ranks.
BK_RRF_K = 60
# Minimum fused RRF score a SEMANTIC-ONLY candidate must reach to be included.
# FTS anchors are exempt (a tsquery hit is a real lexical match against
# SAFE/READY content, never garbage) — applying the floor to them would silently
# drop legitimate FTS results past rank ~6 in the hybrid path while keeping them
# in the keyword-only path. The floor exists to stop a borderline semantic-only
# hit (one that just scraped under the distance cutoff) from surfacing on an
# off-topic query. 1/(60+5) ≈ 0.0154, so a semantic-only candidate must land in
# roughly the top-5 of the semantic list to survive.
BK_RRF_SCORE_FLOOR = 0.015
# Listwise reranker model for post-search reordering (opt-in via rerank=true).
BK_RERANK_MODEL = "claude-haiku-4-5"
# Max chars of chunk content included in the rerank prompt per candidate.
BK_RERANK_SNIPPET_CHARS = 500
# Timeout (seconds) for the async embedding call on the query path. If the
# embedding service is slow, FTS alone fires (graceful degradation).
BK_QUERY_EMBEDDING_TIMEOUT = 5.0

# --- Always-on context cap ---
# Hard char cap for always-on sources injected into every support prompt.
# These bypass query filtering, so unbounded injection blows the token budget.
MAX_ALWAYS_ON_CONTEXT_CHARS = 20_000

# --- Drill-down (agentic read) tunables ---
# Default chunk radius for get_document_window: returns center +/- radius
# chunks (up to 2*radius+1 = 11 chunks ~= 13k chars at typical size).
BK_DRILLDOWN_DEFAULT_RADIUS = 5
# Hard cap on drill-down radius. radius=15 => up to 31 chunks ~= 50k chars;
# bounds how much one read_data call can pull.
BK_DRILLDOWN_MAX_RADIUS = 15
