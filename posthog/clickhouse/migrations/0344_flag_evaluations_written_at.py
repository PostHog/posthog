from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_DATA_TABLE, FLAG_EVALUATIONS_TABLE

# Adds written_at to sharded_flag_evaluations with DEFAULT inserted_at. It then writes the column
# and its minmax index into every existing part. posthog/models/flag_evaluations/sql.py explains why the
# DEFAULT is inserted_at and not now64().
#
# The MATERIALIZE runs as a background mutation, and a mutation computes the DEFAULT that is in
# force when it runs, not the one in force when it was queued. A later change to this DEFAULT must
# therefore wait until system.mutations shows this mutation done on every shard.
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
        f"ALTER TABLE {FLAG_EVALUATIONS_DATA_TABLE} MATERIALIZE COLUMN written_at, MATERIALIZE INDEX written_at_idx",
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
