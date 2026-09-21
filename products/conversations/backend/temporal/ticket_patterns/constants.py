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
# Hydration budget per tick. Above the per-run cap so a stretch of ineligible teams does not
# leave the run short, but bounded so discovery cost cannot grow with the size of the rollout.
MAX_TEAMS_SCANNED_PER_RUN = 150
# The task queue is shared, so a tick takes a slice of a worker's activity slots, not all of them.
MAX_CONCURRENT_DETECTIONS = 10
MAX_TICKETS_PER_TEAM = 150
MAX_MESSAGE_CHARS = 500
MAX_CLUSTERS_PER_RUN = 5

# The banner links to a spike's tickets through the ids query parameter, which the ticket list
# truncates at MAX_TICKET_IDS_FILTER (products/conversations/backend/api/tickets.py). Capping the
# cluster here keeps the count the banner shows equal to the list it opens.
MAX_TICKET_IDS_PER_CLUSTER = 100

# Must be in the LLM gateway `conversations` product allowlist
# (`services/llm-gateway/src/llm_gateway/products/config.py`).
# Not haiku: it splits one outage into separate clusters when customers word it differently
# ("recording down" vs "replays will not load"), which drops each part below the threshold.
DETECTION_MODEL = "claude-sonnet-4-6"
DETECTION_MAX_TOKENS = 2_000

# Twice the widest lookback, so a ticket cannot leave the dedupe set while detection can still
# see it.
REPORTED_TICKET_TTL_SECONDS = LOOKBACK_MINUTES_RANGE[1] * 60 * 2

TICKET_PATTERNS_TRACE_NAMESPACE = UUID("2c9f5e18-4a7b-4c3d-9e1f-6b8a0d2c4e73")
