from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import METRICS4_INPUT_TO_METRICS4_SAMPLES_MV_SELECT

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The storage table and the writable table get the column before the view writes it.
# ClickHouse can add a new column to the end of the sorting key only in the ALTER that adds the column.
# The primary key does not change, so the primary index and the existing parts stay valid.
# Existing rows read the column as 0, which is the hash the view writes for points without bounds.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_samples "
        "ADD COLUMN IF NOT EXISTS histogram_bounds_hash UInt64 AFTER histogram_bounds, "
        "MODIFY ORDER BY (team_id, metric_name, time_bucket, series_fingerprint, histogram_bounds_hash)",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.writable_metrics4_samples "
        "ADD COLUMN IF NOT EXISTS histogram_bounds_hash UInt64 AFTER histogram_bounds",
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_input_to_metrics4_samples MODIFY QUERY\n"
        f"{METRICS4_INPUT_TO_METRICS4_SAMPLES_MV_SELECT()}",
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
