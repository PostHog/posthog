import math
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

# Overflow rolls to the next tick rather than being dropped, so a team waits up to
# ceil(eligible / MAX_TEAMS_PER_RUN) ticks between scans. The detection window is anchored to the
# scan, not to a cursor, so coverage is only gapless while that wait stays inside the team's
# lookback: MAX_TEAMS_PER_RUN * lookback / COORDINATOR_INTERVAL_MINUTES teams, which is 100 at the
# 30 minute floor and 600 at the default. Past that a team on a short window can miss tickets
# between scans, so raise this cap (more calls in flight per tick) or shorten the interval before
# the rollout gets there.
MAX_TEAMS_PER_RUN = 50
# Hydration budget per tick. Above the per-run cap so a stretch of ineligible teams does not
# leave the run short, but bounded so discovery cost cannot grow with the size of the rollout.
MAX_TEAMS_SCANNED_PER_RUN = 150
# The task queue is shared, so a tick takes a slice of a worker's activity slots, not all of them.
MAX_CONCURRENT_DETECTIONS = 10

# The schedule kills a run that outlives its interval (see schedule.py), so everything the run
# does has to fit inside that budget: overrun it and the teams in the later batches are skipped
# with nothing to say so. Collecting the teams happens first and takes its own share, so
# detection gets what is left rather than the whole budget.
RUN_BUDGET_SECONDS = (COORDINATOR_INTERVAL_MINUTES - 1) * 60
COLLECTION_BUDGET_SECONDS = 120
# Slack for the workflow's own overhead between activities, so the last batch finishes inside
# the budget instead of being killed part-way through.
RUN_OVERHEAD_SECONDS = 60

DETECTION_BATCHES_PER_RUN = math.ceil(MAX_TEAMS_PER_RUN / MAX_CONCURRENT_DETECTIONS)
DETECTION_BATCH_BUDGET_SECONDS = (
    RUN_BUDGET_SECONDS - COLLECTION_BUDGET_SECONDS - RUN_OVERHEAD_SECONDS
) // DETECTION_BATCHES_PER_RUN
# The worker sends a heartbeat at most every 0.8 of this, so a cancel for a timed-out detection
# reaches it within that time. Keep it well under the batch budget.
DETECTION_HEARTBEAT_TIMEOUT_SECONDS = 30
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
# Enough for the widest answer the input cap allows. The model echoes back a ticket id per
# grouped ticket, and a UUID is around 25 output tokens, so MAX_TICKETS_PER_TEAM in one cluster
# is already past 2,000 on ids alone. A response cut off mid-JSON fails to parse, and every
# retry sends the same oversized request, so a team in a real incident would get nothing.
DETECTION_MAX_TOKENS = 8_000

# Twice the widest lookback, so a ticket cannot leave the dedupe set while detection can still
# see it.
REPORTED_TICKET_TTL_SECONDS = LOOKBACK_MINUTES_RANGE[1] * 60 * 2

TICKET_PATTERNS_TRACE_NAMESPACE = UUID("2c9f5e18-4a7b-4c3d-9e1f-6b8a0d2c4e73")
