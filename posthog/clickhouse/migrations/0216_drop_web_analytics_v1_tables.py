from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Drop v1 web analytics tables (replaced by web_pre_aggregated_* tables)
operations = [
    # Drop combined views first (they depend on underlying tables)
    run_sql_with_exceptions(
        "DROP VIEW IF EXISTS web_stats_combined SYNC",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        "DROP VIEW IF EXISTS web_bounces_combined SYNC",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # Drop staging tables
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS web_stats_hourly_staging SYNC",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS web_bounces_hourly_staging SYNC",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # Drop hourly tables
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS web_stats_hourly SYNC",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS web_bounces_hourly SYNC",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # Drop daily tables
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS web_stats_daily SYNC",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS web_bounces_daily SYNC",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
