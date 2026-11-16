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
    METRICS = "METRICS"
    # Endpoints (the product) queries
    ENDPOINTS = "ENDPOINTS"


# Workloads whose tables exist only on their own cluster. Routing that moves a query between the main cluster's
# replicas must leave these alone, because the main cluster cannot answer them.
PINNED_CLUSTER_WORKLOADS: frozenset[Workload] = frozenset({Workload.LOGS, Workload.METRICS})
