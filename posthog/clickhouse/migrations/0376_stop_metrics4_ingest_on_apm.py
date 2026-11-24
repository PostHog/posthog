from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The ingestion-apm nodes stop copying metrics into the logs cluster. The ingestion-metrics nodes
# keep writing every row to the metrics cluster, which now serves all metrics reads.
#
# The Kafka view goes first, so the clickhouse-metrics-avro4 group stops consuming before anything
# it writes into disappears. The fan-out views go before the tables they read and write. The
# metrics4 storage tables on the logs cluster stay, and their TTL empties them.
#
# The local stack runs every role on one node and still ingests metrics through this chain, so
# the drop runs only in cloud.
VIEWS = (
    "kafka_metrics_avro4_mv",
    "metrics4_input_to_metrics4_samples",
    "metrics4_input_to_metrics4_series",
    "metrics4_input_to_metrics4_names",
    "metrics4_input_to_metrics4_attributes",
    "metrics4_input_to_metrics4_resource_attributes",
    "metrics4_input_to_metrics_kafka_metrics",
)
TABLES = (
    "kafka_metrics_avro4",
    "metrics4_input",
    "writable_metrics4_samples",
    "writable_metrics4_series",
    "writable_metrics4_names",
    "writable_metrics4_attributes",
    "writable_metrics_kafka_metrics",
)

operations = (
    [
        run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.{name}", node_roles=[NodeRole.APM])
        for name in (*VIEWS, *TABLES)
    ]
    if run_mode().is_deployed_cloud
    else []
)
