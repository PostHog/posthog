from uuid import UUID

COORDINATOR_INTERVAL_MINUTES = 60

# Overflow past these caps stays due and rolls to the next tick; the per-team cap
# keeps one tenant's always-failing channels from starving the rest.
MAX_SUMMARIES_PER_RUN = 50
MAX_SUMMARIES_PER_TEAM_PER_RUN = 10

# Must be in the LLM gateway `conversations` product allowlist
# (`services/llm-gateway/src/llm_gateway/products/config.py`).
SUMMARY_MODEL = "claude-sonnet-5"
SUMMARY_MAX_TOKENS = 10_000

# Thread replies never appear in channel history, so parents this far back are
# scanned for replies that landed inside the period.
STALE_THREAD_LOOKBACK_DAYS = 30

MAX_SUMMARY_ATTEMPTS = 3

# One giant channel must not blow the LLM context or the activity's memory.
MAX_TRANSCRIPT_MESSAGES = 1000
MAX_TRANSCRIPT_CHARS = 150_000
# 200 messages per page; caps the scan even when the window is all filtered-out noise.
MAX_HISTORY_PAGES = 25

CHANNEL_SUMMARY_TRACE_NAMESPACE = UUID("7f3a2b1c-9d4e-4f5a-8b6c-0d1e2f3a4b5c")
