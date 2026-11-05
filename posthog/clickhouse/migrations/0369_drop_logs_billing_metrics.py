from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# Billing reads app_metrics2, never logs_billing_metrics. Drop the view first so inserts into
# logs34 stop writing to the table, then the read table, then the data table.
# The rollup has no TTL, so lift the drop-size guard that would otherwise refuse the drop.
operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.kafka_logs_avro_billing_metrics_mv", node_roles=[NodeRole.LOGS]
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.logs_billing_metrics_distributed SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.logs_billing_metrics SYNC SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.LOGS],
    ),
]
