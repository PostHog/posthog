from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import EVENTS_DATA_TABLE


# Inlined from the former dmat helpers in event/sql.py, which were removed when the
# dynamic-materialized-columns feature was deleted. This already-applied migration must keep
# producing the same additive ALTER it always did. (SQL whitespace is irrelevant to ClickHouse.)
def _add_dmat_string_columns(table: str) -> str:
    pieces = [f"ADD COLUMN IF NOT EXISTS `dmat_string_{i}` Nullable(String)" for i in range(10)]
    return f"ALTER TABLE {table} " + ", ".join(pieces)


operations = [
    # Only add columns to sharded_events and distributed for now (i.e. not the kafka tables / ingestion MV / writable table) to allow profiling backfill performance
    run_sql_with_exceptions(
        _add_dmat_string_columns(EVENTS_DATA_TABLE()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        _add_dmat_string_columns("events"),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
