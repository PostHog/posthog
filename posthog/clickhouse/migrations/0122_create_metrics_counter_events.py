from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.clickhouse.custom_metrics import (
    CREATE_CUSTOM_METRICS_COUNTER_EVENTS_TABLE,
    CREATE_CUSTOM_METRICS_COUNTERS_VIEW,
    CUSTOM_METRICS_VIEW,
)

operations = [
    run_sql_with_exceptions(
        CREATE_CUSTOM_METRICS_COUNTER_EVENTS_TABLE, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    run_sql_with_exceptions(CREATE_CUSTOM_METRICS_COUNTERS_VIEW, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(
        CUSTOM_METRICS_VIEW(include_counters=True), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
]
