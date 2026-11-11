from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The metrics cluster serves every metrics read and write: HogQL reads it through Workload.METRICS,
# PromQL goes to its Snuffle, and migration 0376 stopped the ingestion-apm nodes writing metrics4
# into the logs cluster. The logs cluster's copy is no longer read or written, so it is dropped
# to free disk there instead of waiting for its TTL.
#
# The view reads metrics4_samples, so it goes first. The tables are replicated, but each drop
# removes only this cluster's replicas. The metrics cluster keeps its own. These tables can be
# larger than the server's max_table_size_to_drop, which the drops lift.
#
# The local stack runs every role on one node and still serves metrics from these tables, so the
# drop runs only in cloud.
TABLES = (
    "metrics4_samples",
    "metrics4_series",
    "metrics4_names",
    "metrics4_attributes",
    "metrics_kafka_metrics",
)

operations = (
    [
        run_sql_with_exceptions(f"DROP VIEW IF EXISTS {DB}.metrics4_view", node_roles=[NodeRole.LOGS]),
        *[
            run_sql_with_exceptions(
                f"DROP TABLE IF EXISTS {DB}.{name} SETTINGS max_table_size_to_drop = 0",
                node_roles=[NodeRole.LOGS],
            )
            for name in TABLES
        ],
    ]
    if run_mode().is_deployed_cloud
    else []
)
