from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.web_preaggregated.team_selection import (
    DEFAULT_ENABLED_TEAM_IDS,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    run_sql_with_exceptions(
        WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL(DEFAULT_ENABLED_TEAM_IDS),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL(on_cluster=False),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
