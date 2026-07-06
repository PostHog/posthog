MAX_ATTEMPTS = 5
SCORE_THRESHOLD = 0.5
RERANK_TOP_K = 5
# Ticket types whose replies may ever be published to the (untrusted) ticket author.
# diagnostic/account_billing draw on project data and must stay private regardless of settings.
PUBLISHABLE_TICKET_TYPES = {"how_to"}
RETRIEVE_LIMIT = 15
DRAFT_POLL_SECONDS = 900
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

# Base read scopes every draft gets (when the team has NOT opted into ai_diagnostics_enabled):
# BK, docs, project metadata, taxonomy, and config reads that return no raw customer rows.
BASE_DRAFT_SCOPES: list[str] = [
    "business_knowledge:read",
    "project:read",
    "event_definition:read",
    "property_definition:read",
    "feature_flag:read",
    "experiment:read",
    "survey:read",
    "action:read",
    "annotation:read",
    "dashboard:read",
]

# When the team opted into ai_diagnostics_enabled, the draft gets the "read_only" preset
# (all reads, including customer data tools like execute-sql, session recordings, error
# tracking, logs). The preset string is passed directly to CustomPromptSandboxContext.
# The prompt layer + support_review_reply_activity backstop external-connection data.
DIAGNOSTIC_SCOPES_PRESET = "read_only"

# Sandbox agent model for the draft step.
DRAFT_MODEL = "claude-sonnet-4-6"
DRAFT_RUNTIME_ADAPTER = "claude"

# One-line bias appended to refine/draft/validate prompts so each step focuses on what the
# ticket type actually needs answered.
TICKET_TYPE_HINTS: dict[str, str] = {
    "how_to": "This is a how-to/usage question — answer it from product documentation and the team's knowledge base.",
    "diagnostic": "This is a diagnostic ticket — the customer reports something broken or unexpected for their account; focus on what's failing and why.",
    "account_billing": "This is an account/billing question — focus on the customer's plan, usage, limits, and billing specifics.",
    "unactionable": "This ticket has no answerable support question.",
}
