from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.custom_metrics import (
    CUSTOM_METRICS_REPLICATION_QUEUE_VIEW,
    CUSTOM_METRICS_SERVER_CRASH_VIEW,
    CUSTOM_METRICS_TABLE_SIZES_VIEW,
    CUSTOM_METRICS_TEST_VIEW,
    CUSTOM_METRICS_VIEW,
)

# The custom_metrics views back the predefined_query_handler at :8443/metrics
# (see ansible/roles/clickhouse/templates/config.d/http_custom_metrics.xml).
# Existing migrations only created them on NodeRole.DATA, so the satellite
# clusters return scrape errors (up=0) for the clickhouse-custom-metrics-cross-account
# job, which breaks the table-size panels for ai_events and friends.
#
# Source views included here are the ones that do not depend on tables that
# only live on DATA:
# - custom_metrics_test: constant
# - custom_metrics_replication_queue: system.replication_queue
# - custom_metrics_table_sizes: system.tables
# - custom_metrics_server_crash: system.crash_log (configured via the role-level
#   log_tables.xml on every CH host)
#
# Excluded:
# - custom_metrics_events_recent_lag: depends on events_recent (DATA-only)
# - custom_metrics_counters: depends on custom_metrics_counter_events table
#   (DATA-only, created in 0122)

SATELLITE_NODE_ROLES = [
    NodeRole.AI_EVENTS,
    NodeRole.AUX,
    NodeRole.OPS,
    NodeRole.SESSIONS,
]

operations = [
    # Defensive: AUX/AI_EVENTS migrations have already created tables in `posthog`
    # on those clusters, but OPS/SESSIONS are less exercised. No-op when the
    # database already exists.
    run_sql_with_exceptions(
        "CREATE DATABASE IF NOT EXISTS posthog",
        node_roles=SATELLITE_NODE_ROLES,
    ),
    run_sql_with_exceptions(
        CUSTOM_METRICS_TEST_VIEW(),
        node_roles=SATELLITE_NODE_ROLES,
    ),
    run_sql_with_exceptions(
        CUSTOM_METRICS_REPLICATION_QUEUE_VIEW(),
        node_roles=SATELLITE_NODE_ROLES,
    ),
    run_sql_with_exceptions(
        CUSTOM_METRICS_TABLE_SIZES_VIEW(),
        node_roles=SATELLITE_NODE_ROLES,
    ),
    run_sql_with_exceptions(
        CUSTOM_METRICS_SERVER_CRASH_VIEW(),
        node_roles=SATELLITE_NODE_ROLES,
    ),
    run_sql_with_exceptions(
        CUSTOM_METRICS_VIEW(
            include_counters=False,
            include_server_crash=True,
            include_table_sizes=True,
            include_events_recent_lag=False,
        ),
        node_roles=SATELLITE_NODE_ROLES,
    ),
]
