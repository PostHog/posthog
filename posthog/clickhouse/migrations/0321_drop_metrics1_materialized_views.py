from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# metrics2 owns ingestion and attribute extraction now. Remove the legacy metrics1
# views so Kafka inserts no longer write to metrics1, metric_samples1, or metric_series1.
operations = [
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics1_to_metric_attributes", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics1_to_resource_attributes", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS kafka_metrics_avro_mv", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS kafka_metrics_avro_to_metric_samples", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS kafka_metrics_avro_to_metric_series", node_roles=[NodeRole.LOGS]),
]
