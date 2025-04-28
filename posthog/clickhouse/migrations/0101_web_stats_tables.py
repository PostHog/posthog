from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.web_preaggregated.sql import (
    WEB_OVERVIEW_METRICS_DAILY_SQL,
    DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL,
    WEB_STATS_DAILY_SQL,
    DISTRIBUTED_WEB_STATS_DAILY_SQL,
)

operations = [
    # Create base tables
    run_sql_with_exceptions(WEB_OVERVIEW_METRICS_DAILY_SQL()),
    run_sql_with_exceptions(WEB_OVERVIEW_METRICS_DAILY_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
    run_sql_with_exceptions(WEB_STATS_DAILY_SQL()),
    run_sql_with_exceptions(WEB_STATS_DAILY_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
    
    # Create distributed tables
    run_sql_with_exceptions(DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_WEB_STATS_DAILY_SQL()),
] 