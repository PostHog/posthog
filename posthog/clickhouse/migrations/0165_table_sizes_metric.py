from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.clickhouse.custom_metrics import CUSTOM_METRICS_TABLE_SIZES_VIEW

operations = [
    run_sql_with_exceptions(CUSTOM_METRICS_TABLE_SIZES_VIEW(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
]
