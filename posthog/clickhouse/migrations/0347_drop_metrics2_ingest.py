from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# metrics4 owns metrics ingest now and HogQL reads only metrics4. Stop the metrics2 chain:
# drop the Kafka view first so the consumer stops, then the Kafka table, the views out of
# metrics2_input, and metrics2_input. The metrics2 and metrics3 tables stay until their TTL
# clears the rows. None of these objects is replicated, so no SYNC.
operations = [
    run_sql_with_exceptions("DROP TABLE IF EXISTS kafka_metrics_avro2_mv", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS kafka_metrics_avro2", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics2_input_to_metrics", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics2_input_to_metric_series", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics2_input_to_metric_attributes", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics2_input_to_resource_attributes", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics2_input_to_metric_series3", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics2_input_to_metric_attributes3", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics2_input_to_resource_attributes3", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics2_input_to_metric_names3", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS metrics2_input", node_roles=[NodeRole.LOGS]),
]
