from datetime import UTC, datetime, timedelta

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# HogQL reads the $session_id property as nullIf(nullIf(`$session_id`, ''), 'null'), and skip-index analysis only
# engages when the index expression matches that operand exactly, so the index is on the expression rather than the
# bare column (which stays invisible through the wrapper).
ADD_BLOOM_FILTER_INDEX_SHARDED_EVENTS = """
ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `bloom_filter_$session_id` nullIf(nullIf(`$session_id`, ''), 'null')
TYPE bloom_filter
GRANULARITY 1
"""


def _recent_partition_ids() -> list[str]:
    current = datetime.now(UTC).date().replace(day=1)
    previous = (current - timedelta(days=1)).replace(day=1)
    return [f"{d.year}{d.month:02d}" for d in (previous, current)]


# Backfill only the two most recent monthly partitions: the last full-table MATERIALIZE INDEX on this table
# (0055) ran for weeks, and session-scoped queries rarely look back further than this anyway. Both partitions go
# in one ALTER because a second statement would trip number_of_mutations_to_throw while the first is unfinished.
MATERIALIZE_BLOOM_FILTER_INDEX_SHARDED_EVENTS = "ALTER TABLE sharded_events " + ", ".join(
    f"MATERIALIZE INDEX `bloom_filter_$session_id` IN PARTITION ID '{partition_id}'"
    for partition_id in _recent_partition_ids()
)

operations = [
    run_sql_with_exceptions(
        ADD_BLOOM_FILTER_INDEX_SHARDED_EVENTS,
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        MATERIALIZE_BLOOM_FILTER_INDEX_SHARDED_EVENTS,
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
