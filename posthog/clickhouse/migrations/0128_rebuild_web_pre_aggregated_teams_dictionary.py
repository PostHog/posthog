from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.cluster import NodeRole
from posthog.models.web_preaggregated.team_selection import (
    DROP_WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL,
)

operations = [
    run_sql_with_exceptions(
        DROP_WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL(on_cluster=False),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL(on_cluster=False),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
