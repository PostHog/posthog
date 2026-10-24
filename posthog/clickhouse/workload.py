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
    # Tables that exist only on the events cluster. Set by routing from the printed SQL, never by a caller.
    NEW_EVENTS_CLUSTER = "NEW_EVENTS_CLUSTER"
    # Endpoints (the product) queries
    ENDPOINTS = "ENDPOINTS"


# A query on one of these can be moved to another cluster by the table it reads. LOGS and ENDPOINTS already pin a host.
MAIN_CLUSTER_WORKLOADS = (Workload.DEFAULT, Workload.ONLINE, Workload.OFFLINE)
# A query on one of these names the only cluster that holds its tables, so no override may move it.
PINNED_CLUSTER_WORKLOADS = (Workload.LOGS, Workload.NEW_EVENTS_CLUSTER)
