from enum import StrEnum


# The workload records intent in the query tag. The pod's CLICKHOUSE_HOST decides which replicas run the query.
# See .agents/skills/writing-clickhouse-queries/references/choosing-a-workload.md before you pick one.
class Workload(StrEnum):
    # Follows the caller: sync_execute resolves it to ONLINE or OFFLINE. Avoid in new call sites.
    DEFAULT = "DEFAULT"
    # A person waits on screen for the result
    ONLINE = "ONLINE"
    # No person waits: scheduled jobs, exports, backfills, recomputes. Turns off hedged requests.
    OFFLINE = "OFFLINE"
    # Tables that exist only on the logs cluster
    LOGS = "LOGS"
    NEW_EVENTS_CLUSTER = "NEW_EVENTS_CLUSTER"
    # Endpoints (the product) queries
    ENDPOINTS = "ENDPOINTS"
