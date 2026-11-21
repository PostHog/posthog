from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import METRICS4_INPUT_TO_METRICS4_SAMPLES_MV_SELECT
from posthog.run_mode import run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# points_received counts every point a metrics4_samples row was built from, so the points the
# 10,000-per-row cap drops can be counted. The storage tables and the writable table get the column
# before the view writes it. Existing rows read 0.
#
# In cloud the ingestion-metrics nodes write to the metrics cluster, and 0379 dropped the logs
# cluster's metrics4 tables. The local stack still runs the chain on the logs and apm roles.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_samples "
        "ADD COLUMN IF NOT EXISTS points_received SimpleAggregateFunction(sum, UInt64) AFTER _topic",
        node_roles=[NodeRole.METRICS] if run_mode().is_deployed_cloud else [NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.writable_metrics4_samples "
        "ADD COLUMN IF NOT EXISTS points_received SimpleAggregateFunction(sum, UInt64) AFTER _topic",
        node_roles=[NodeRole.INGESTION_METRICS] if run_mode().is_deployed_cloud else [NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_input_to_metrics4_samples MODIFY QUERY\n"
        f"{METRICS4_INPUT_TO_METRICS4_SAMPLES_MV_SELECT()}",
        node_roles=[NodeRole.INGESTION_METRICS] if run_mode().is_deployed_cloud else [NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
