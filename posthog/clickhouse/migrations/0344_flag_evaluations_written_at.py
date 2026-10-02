from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_DATA_TABLE, FLAG_EVALUATIONS_TABLE

# Parts that exist before this migration do not store written_at. They read it through the DEFAULT
# until the backfill_materialized_column job materializes the column and its index, one partition
# at a time. This migration does not run that MATERIALIZE itself. The cluster sets
# number_of_mutations_to_throw = 1, so a squash or delete mutation that is still running on this
# table would reject the MATERIALIZE and fail the deploy.
#
# The read table gets the column last, so a query that names written_at never reaches a shard that
# lacks it. AFTER inserted_at matches the column order that a fresh CREATE TABLE renders.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {FLAG_EVALUATIONS_DATA_TABLE} "
        "ADD COLUMN IF NOT EXISTS written_at DateTime64(6, 'UTC') DEFAULT inserted_at AFTER inserted_at, "
        "ADD INDEX IF NOT EXISTS written_at_idx written_at TYPE minmax GRANULARITY 1",
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {FLAG_EVALUATIONS_TABLE} ADD COLUMN IF NOT EXISTS written_at DateTime64(6, 'UTC') AFTER inserted_at",
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
