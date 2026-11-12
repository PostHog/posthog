from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The metrics1 and metrics2 families on the logs cluster are no longer read or written.
# Migrations 0321 and 0347 removed their ingest, and every metrics read goes to the metrics
# cluster's metrics4 tables through Workload.METRICS. They are dropped to free disk instead of
# waiting for a TTL that metrics1 lacks and metrics2 stalled on.
#
# The Distributed tables read the storage tables, so they go first. writable_metrics1 is a
# Distributed proxy to metrics1 on the ingestion-apm nodes that nothing writes to any more.
# These tables can be larger than the server's max_table_size_to_drop, which the drops lift.
#
# metric_samples1, metric_series1 and their readers stay. The local stack runs every role on
# one node and still declares these tables, so the drop runs only in cloud.
DISTRIBUTED_TABLES = (
    "metrics",
    "metrics_distributed",
    "metric_series_distributed",
    "metric_attributes_distributed",
)

STORAGE_TABLES = (
    "metrics1",
    "metric_attributes",
    "metrics2",
    "metric_series2",
    "metric_attributes2",
    "metrics2_backfill_series",
    "metric_names3",
    "metric_series3",
    "metric_attributes3",
)

operations = (
    [
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {DB}.writable_metrics1",
            node_roles=[NodeRole.APM],
        ),
        *[
            run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.{name}", node_roles=[NodeRole.LOGS])
            for name in DISTRIBUTED_TABLES
        ],
        *[
            run_sql_with_exceptions(
                f"DROP TABLE IF EXISTS {DB}.{name} SETTINGS max_table_size_to_drop = 0",
                node_roles=[NodeRole.LOGS],
            )
            for name in STORAGE_TABLES
        ],
    ]
    if run_mode().is_deployed_cloud
    else []
)
