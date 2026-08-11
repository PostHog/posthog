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

operations = [
    run_sql_with_exceptions(
        ADD_BLOOM_FILTER_INDEX_SHARDED_EVENTS,
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
