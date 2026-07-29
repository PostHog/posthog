from uuid import UUID

COORDINATOR_INTERVAL_MINUTES = 60

# Fan-out cap per tick: overflow stays due and rolls to the next hourly tick.
MAX_SUMMARIES_PER_RUN = 50
# One tenant's channels (e.g. a batch of always-failing bindings that stay due) must
# not monopolize the global cap and starve other teams.
MAX_SUMMARIES_PER_TEAM_PER_RUN = 10

# Must be in the LLM gateway `conversations` product allowlist
# (`services/llm-gateway/src/llm_gateway/products/config.py`).
SUMMARY_MODEL = "claude-sonnet-5"
# Generous so a busy period never truncates mid-list; a short prompt-enforced summary
# stops well under this on quiet channels.
SUMMARY_MAX_TOKENS = 10_000

# How far before the period to scan for older threads that got replies inside it —
# a customer replying to last week's thread still counts as period activity.
STALE_THREAD_LOOKBACK_DAYS = 30

# Attempts for the single summarize activity; the activity captures to error
# tracking on its final attempt.
MAX_SUMMARY_ATTEMPTS = 3

# Bounds on the in-memory transcript so one giant channel can't blow the LLM
# context or the activity's memory. Oldest messages are dropped first.
MAX_TRANSCRIPT_MESSAGES = 1000
MAX_TRANSCRIPT_CHARS = 150_000

# Stable namespace for deterministic per-summary trace ids.
CHANNEL_SUMMARY_TRACE_NAMESPACE = UUID("7f3a2b1c-9d4e-4f5a-8b6c-0d1e2f3a4b5c")
