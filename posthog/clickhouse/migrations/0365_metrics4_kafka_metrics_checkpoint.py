from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    METRICS4_INPUT_TO_METRICS_KAFKA_METRICS_MV,
    WRITABLE_METRICS_KAFKA_METRICS_TABLE_SQL,
)

# metrics_kafka_metrics already exists on the logs cluster: 0309 created it, and 0340 dropped the
# only view that wrote to it. The writable table must exist before the view that inserts into it.
operations = [
    run_sql_with_exceptions(WRITABLE_METRICS_KAFKA_METRICS_TABLE_SQL(), node_roles=[NodeRole.APM]),
    run_sql_with_exceptions(METRICS4_INPUT_TO_METRICS_KAFKA_METRICS_MV(), node_roles=[NodeRole.APM]),
]
