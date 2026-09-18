from uuid import UUID

COORDINATOR_INTERVAL_MINUTES = 15

MASTER_FLAG = "product-support-ticket-patterns"

# Three hours, not one: a spike in a slow-moving area arrives as a trickle, and an hour-wide
# window never holds enough of it at once to look like a spike.
DEFAULT_LOOKBACK_MINUTES = 180

DEFAULT_MIN_TICKETS = 3
DEFAULT_MIN_REQUESTERS = 3

LOOKBACK_MINUTES_RANGE = (30, 1440)
MIN_TICKETS_RANGE = (2, 50)
MIN_REQUESTERS_RANGE = (2, 50)

# Overflow rolls to the next tick rather than being dropped.
MAX_TEAMS_PER_RUN = 50
MAX_TICKETS_PER_TEAM = 150
MAX_MESSAGE_CHARS = 500
MAX_CLUSTERS_PER_RUN = 5

# Must be in the LLM gateway `conversations` product allowlist
# (`services/llm-gateway/src/llm_gateway/products/config.py`).
# Not haiku: it splits one outage into separate clusters when customers word it differently
# ("recording down" vs "replays will not load"), which drops each part below the threshold.
DETECTION_MODEL = "claude-sonnet-4-6"
# Enough for the widest answer the input cap allows. The model echoes back a ticket id per
# grouped ticket, and a UUID is around 25 output tokens, so MAX_TICKETS_PER_TEAM in one cluster
# is already past 2,000 on ids alone. A response cut off mid-JSON fails to parse, and every
# retry sends the same oversized request, so a team in a real incident would get nothing.
DETECTION_MAX_TOKENS = 8_000

# Twice the widest lookback, so a ticket cannot leave the dedupe set while detection can still
# see it.
REPORTED_TICKET_TTL_SECONDS = LOOKBACK_MINUTES_RANGE[1] * 60 * 2

TICKET_PATTERNS_TRACE_NAMESPACE = UUID("2c9f5e18-4a7b-4c3d-9e1f-6b8a0d2c4e73")
