from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.web_preaggregated.sql import (
    WEB_BOUNCES_COMBINED_VIEW_SQL,
    WEB_BOUNCES_DAILY_SQL,
    WEB_BOUNCES_HOURLY_SQL,
    WEB_STATS_COMBINED_VIEW_SQL,
    WEB_STATS_DAILY_SQL,
    WEB_STATS_HOURLY_SQL,
)

operations = [
    # Create daily tables
    run_sql_with_exceptions(WEB_STATS_DAILY_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(WEB_BOUNCES_DAILY_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    # Create hourly tables
    run_sql_with_exceptions(WEB_STATS_HOURLY_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(WEB_BOUNCES_HOURLY_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    # Create staging tables for hourly processing
    run_sql_with_exceptions(
        WEB_STATS_HOURLY_SQL().replace("web_stats_hourly", "web_stats_hourly_staging"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        WEB_BOUNCES_HOURLY_SQL().replace("web_bounces_hourly", "web_bounces_hourly_staging"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # Create combined views that merge daily and hourly data
    run_sql_with_exceptions(WEB_STATS_COMBINED_VIEW_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(WEB_BOUNCES_COMBINED_VIEW_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
]
