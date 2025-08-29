from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.clickhouse.custom_metrics import (
    CUSTOM_METRICS_EVENTS_RECENT_LAG_VIEW,
    CUSTOM_METRICS_REPLICATION_QUEUE_VIEW,
    CUSTOM_METRICS_TEST_VIEW,
    CUSTOM_METRICS_VIEW,
)

operations = [
    run_sql_with_exceptions(CUSTOM_METRICS_REPLICATION_QUEUE_VIEW(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(CUSTOM_METRICS_TEST_VIEW(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(CUSTOM_METRICS_EVENTS_RECENT_LAG_VIEW(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(
        CUSTOM_METRICS_VIEW(include_counters=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
]
