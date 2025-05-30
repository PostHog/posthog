from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions, NodeRole
from posthog.clickhouse.custom_metrics import (
    CREATE_CUSTOM_METRICS_COUNTER_EVENTS_TABLE,
    CREATE_CUSTOM_METRICS_COUNTERS_VIEW,
    CUSTOM_METRICS_VIEW,
)

operations = [
    run_sql_with_exceptions(CREATE_CUSTOM_METRICS_COUNTER_EVENTS_TABLE, node_role=NodeRole.ALL),
    run_sql_with_exceptions(CREATE_CUSTOM_METRICS_COUNTERS_VIEW, node_role=NodeRole.ALL),
    run_sql_with_exceptions(CUSTOM_METRICS_VIEW(), node_role=NodeRole.ALL),
]
