MAX_ATTEMPTS = 5
SCORE_THRESHOLD = 0.5
RERANK_TOP_K = 5
# Ticket types whose replies may ever be published to the (untrusted) ticket author.
# diagnostic/account_billing draw on project data and must stay private regardless of settings.
PUBLISHABLE_TICKET_TYPES = {"how_to"}
RETRIEVE_LIMIT = 15
DRAFT_POLL_SECONDS = 600
WIDEN_RADIUS = 3

# Temporal records every activity input/output in workflow history (per-payload limit ~2 MiB,
# total history limit ~50 MiB). This loop replays ticket_context + chunks into refine/draft/
# validate across up to MAX_ATTEMPTS iterations, so bound both at the source to keep history
# small. Downstream prompts already slice harder than these caps, so nothing useful is lost.
MAX_TICKET_CONTEXT_CHARS = 16000
MAX_CHUNK_CONTENT_CHARS = 2000
MAX_CHUNKS = 25
# The draft's `sources` are model-controlled (count + excerpt length), so bound them before
# they flow into validate's input and the workflow's best-so-far tracking.
MAX_SOURCES = 25
MAX_EXCERPT_CHARS = 1000
# The safety filter and draft prompt must review/consume the exact same ticket text. This
# constant is the single source of truth for that window; the workflow slices once and passes
# the result to both activities so there's no mismatch.
MAX_SAFETY_REVIEWED_CHARS = 6000

# Plain-LLM utility calls go through the internal LLM gateway via the raw Anthropic SDK —
# the gateway captures $ai_generation itself, so no langchain wrapper.
# UTILITY_MODEL (haiku) is cheap/fast for query refinement. Validation grounds correct replies
# against sources, so it uses a stronger sonnet-class model to avoid under-scoring good answers.
UTILITY_MODEL = "claude-haiku-4-5"
VALIDATOR_MODEL = "claude-sonnet-4-6"

# Bound each utility LLM call so a dropped/slow gateway connection fails fast and Temporal
# retries (per each activity's retry policy) instead of the SDK hanging on its long default
# timeout. Kept under the activities' 2-minute start_to_close so the SDK error wins (a retryable
# ApplicationError) rather than a Temporal ActivityTaskTimeout.
LLM_REQUEST_TIMEOUT_SECONDS = 90.0

# One-shot triage of each ticket up front. `how_to`/`account_billing` are retrieval-solvable;
# `diagnostic` needs the customer's own data (drives PR 3's wider read scopes); `unactionable`
# (spam, bare feedback, no question) short-circuits before the expensive draft loop.
TICKET_TYPES = ("how_to", "diagnostic", "account_billing", "unactionable")

# Base read scopes every draft gets: BK search/window + docs-search (Inkeep RAG over the
# official PostHog docs). Both read-only; persistence is a plain activity, no write scope needed.
BASE_DRAFT_SCOPES = ["business_knowledge:read", "project:read"]

# Extra read scopes granted only to `diagnostic` tickets so the agent can investigate the
# customer's own data. All confirmed valid scope objects in posthog/scopes.py.
# - query:read + insight:read together unlock execute-sql/HogQL (query:read alone does NOT;
#   the execute-sql tool requires both, and there's no separate `events` scope — query:read
#   "covers query and events endpoints").
# - logs:read unlocks query-logs (a separate scope, not implied by query:read); harmless no-op
#   on teams without the logs feature flag.
# - error_tracking:read (issues list/get/events), session_recording:read (recording get/summaries).
#
# query:read also exposes execute-sql's optional `connectionId`, which can target external
# direct-query data sources — outside the "customer's own PostHog project data" boundary these
# scopes are meant to cover. There is no narrower project-only query scope to grant instead, so
# the direct-connection path is closed at the prompt layer (the diagnostic instructions forbid
# connectionId / external sources) and backstopped by support_review_reply_activity, which treats any
# external-connection-sourced data in the reply as unsafe.
DIAGNOSTIC_DRAFT_SCOPES = [
    "error_tracking:read",
    "query:read",
    "insight:read",
    "session_recording:read",
    "logs:read",
]

# One-line bias appended to refine/draft/validate prompts so each step focuses on what the
# ticket type actually needs answered.
TICKET_TYPE_HINTS: dict[str, str] = {
    "how_to": "This is a how-to/usage question — answer it from product documentation and the team's knowledge base.",
    "diagnostic": "This is a diagnostic ticket — the customer reports something broken or unexpected for their account; focus on what's failing and why.",
    "account_billing": "This is an account/billing question — focus on the customer's plan, usage, limits, and billing specifics.",
    "unactionable": "This ticket has no answerable support question.",
}
