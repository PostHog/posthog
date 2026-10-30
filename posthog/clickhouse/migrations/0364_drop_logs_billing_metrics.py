from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Billing reads app_metrics2, never logs_billing_metrics. Drop the view first so inserts into
# logs34 stop writing to the table, then the read table, then the data table.
operations = [
    run_sql_with_exceptions("DROP TABLE IF EXISTS kafka_logs_avro_billing_metrics_mv", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS logs_billing_metrics_distributed", node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions("DROP TABLE IF EXISTS logs_billing_metrics", node_roles=[NodeRole.LOGS]),
]
