from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.clickhouse.custom_metrics import CUSTOM_METRICS_TABLE_SIZES_VIEW, CUSTOM_METRICS_VIEW

operations = [
    run_sql_with_exceptions(CUSTOM_METRICS_TABLE_SIZES_VIEW(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(
        CUSTOM_METRICS_VIEW(include_counters=True, include_server_crash=True, include_table_sizes=True),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
