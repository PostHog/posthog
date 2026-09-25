from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.clickhouse.custom_metrics import CUSTOM_METRICS_SERVER_CRASH_VIEW, CUSTOM_METRICS_VIEW

operations = [
    # ClickHouse creates system.crash_log on the first flush, not at startup, so a node that
    # never crashed has no table for the view below to resolve.
    run_sql_with_exceptions("SYSTEM FLUSH LOGS", node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(CUSTOM_METRICS_SERVER_CRASH_VIEW(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(
        CUSTOM_METRICS_VIEW(include_counters=True, include_server_crash=True),
        node_roles=[NodeRole.DATA],
    ),
]
