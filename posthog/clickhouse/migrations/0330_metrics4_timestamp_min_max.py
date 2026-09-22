from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import METRICS4_INPUT_TO_METRICS4_SAMPLES_MV_SELECT

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The alias columns store nothing, and the indexes cover the parts that arrive
# after this migration. The parts that are already on disk keep the granule
# bounds they have and leave with their TTL, so no MATERIALIZE INDEX runs here.
operations = [
    run_sql_with_exceptions(
        f"""
ALTER TABLE {DB}.metrics4_samples
    ADD COLUMN IF NOT EXISTS timestamp_min DateTime64(6) ALIAS arrayMin(timestamp_arr),
    ADD COLUMN IF NOT EXISTS timestamp_max DateTime64(6) ALIAS arrayMax(timestamp_arr)
""",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_samples "
        "ADD INDEX IF NOT EXISTS idx_timestamp_min_minmax timestamp_min TYPE minmax GRANULARITY 1",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_samples "
        "ADD INDEX IF NOT EXISTS idx_timestamp_max_minmax timestamp_max TYPE minmax GRANULARITY 1",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    # A day bucket takes time_bucket out of the sort key in effect. The two new
    # indexes carry the time filter that the hour bucket carried before.
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_input_to_metrics4_samples MODIFY QUERY\n{METRICS4_INPUT_TO_METRICS4_SAMPLES_MV_SELECT()}",
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
