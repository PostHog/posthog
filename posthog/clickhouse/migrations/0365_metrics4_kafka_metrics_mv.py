from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    METRICS4_INPUT_TO_METRICS_KAFKA_METRICS_MV,
    WRITABLE_METRICS_KAFKA_METRICS_TABLE_SQL,
)

# Restores the consumer-lag bookkeeping for the metrics Kafka consumer. 0340 dropped the only writer of
# metrics_kafka_metrics, and the metrics4 ingest chain on the apm nodes never got one. The MV reads the
# Null input table, so it adds one small aggregated block per consumed Kafka block and no extra Kafka reads.
# The dev apm nodes already have the Distributed proxy, so the CREATE TABLE is a no-op there.
operations = [
    run_sql_with_exceptions(
        WRITABLE_METRICS_KAFKA_METRICS_TABLE_SQL(),
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        METRICS4_INPUT_TO_METRICS_KAFKA_METRICS_MV(),
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
