from django.conf import settings

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_router.config import Pool, QueryClass
from posthog.clickhouse.query_tagging import Feature, Product, QueryTags, is_api_key_access_method
from posthog.clickhouse.workload import Workload

_ROUTED_WORKLOADS: dict[Workload, Pool] = {
    Workload.OFFLINE: Pool.OFFLINE,
    Workload.ONLINE: Pool.ONLINE,
}

# Operational users run maintenance that the router must never delay. BATCH_EXPORT and BILLING are
# the users the ClickHouse kill switch also leaves alone.
_EXEMPT_USERS: frozenset[ClickHouseUser] = frozenset(
    {
        ClickHouseUser.MIGRATIONS,
        ClickHouseUser.OPS,
        ClickHouseUser.BACKUPS,
        ClickHouseUser.PART_BREAKER,
        ClickHouseUser.DELETION_EXECUTOR,
        ClickHouseUser.DICT_READER,
        ClickHouseUser.BATCH_EXPORT,
        ClickHouseUser.BILLING,
    }
)

_PROCESS_QUERY_TASK_ID = "posthog.tasks.tasks.process_query_task"

_ASYNC_FEATURES: frozenset[Feature] = frozenset({Feature.ALERTING, Feature.POSTHOG_AI, Feature.MCP})


def pool_for(*, workload: Workload, team_id: int | None, explicit_client: bool) -> Pool | None:
    # An explicit client and a team with its own cluster do not run on the shared nodes the router counts.
    if explicit_client:
        return None
    if team_id is not None and str(team_id) in settings.CLICKHOUSE_PER_TEAM_SETTINGS:
        return None
    return _ROUTED_WORKLOADS.get(workload)


def classify_query(tags: QueryTags, ch_user: ClickHouseUser) -> QueryClass | None:
    if ch_user in _EXEMPT_USERS or tags.feature == Feature.QUERY_ROUTER:
        return None
    # The app loads most insights through the query task, which runs a request's query for a caller
    # that polls for the result. The task carries the tags of that request, so its query keeps the
    # caller's class. This rule comes before the other async rules because a person who calls
    # PostHog AI or MCP over HTTP waits for the answer.
    if tags.kind == "request" or tags.id == _PROCESS_QUERY_TASK_ID:
        return QueryClass.API if is_api_key_access_method(tags.access_method) else QueryClass.INTERACTIVE
    if tags.feature in _ASYNC_FEATURES or tags.product == Product.MAX_AI:
        return QueryClass.ASYNC
    return QueryClass.BACKGROUND
