from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_SQL, WEB_STATS_SQL

operations = [
    run_sql_with_exceptions(WEB_STATS_SQL(on_cluster=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(WEB_BOUNCES_SQL(on_cluster=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    # Create staging tables as well for partition swapping
    run_sql_with_exceptions(
        WEB_STATS_SQL(table_name="web_pre_aggregated_stats_staging", on_cluster=False),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        WEB_BOUNCES_SQL(table_name="web_pre_aggregated_bounces_staging", on_cluster=False),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
