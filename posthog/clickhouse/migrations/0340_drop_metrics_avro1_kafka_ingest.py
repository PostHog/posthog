from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# metrics2 and metrics4 own metrics ingest now. 0321 removed the last views that wrote
# metrics data out of kafka_metrics_avro, leaving only the consumer-lag view, so the
# consumer still reads clickhouse_metrics for bookkeeping alone. Drop the view first,
# then the Kafka table it reads. Neither is replicated, so no SYNC.
operations = [
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS kafka_metrics_avro_kafka_metrics_mv",
        node_roles=[NodeRole.LOGS, NodeRole.APM],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS kafka_metrics_avro",
        node_roles=[NodeRole.LOGS, NodeRole.APM],
    ),
]
