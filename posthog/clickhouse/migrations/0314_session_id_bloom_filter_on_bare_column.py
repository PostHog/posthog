from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DROP_EXPRESSION_BLOOM_FILTER_INDEX = "ALTER TABLE sharded_events DROP INDEX IF EXISTS `bloom_filter_$session_id`"

ADD_BARE_COLUMN_BLOOM_FILTER_INDEX = """
ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `bloom_filter_$session_id` `$session_id`
TYPE bloom_filter(0.01)
GRANULARITY 1
"""

operations = [
    run_sql_with_exceptions(
        DROP_EXPRESSION_BLOOM_FILTER_INDEX,
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_BARE_COLUMN_BLOOM_FILTER_INDEX,
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
