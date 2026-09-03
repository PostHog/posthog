from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Migration 0293 indexed nullIf(nullIf(`$session_id`, ''), 'null'), the null-scrubbed read HogQL prints for
# properties.$session_id. That index cannot serve the queries that filter on a session id: HogQL's default
# transform_null_in=1 makes ClickHouse plan `in()` as `nullIn()`, which the bloom-filter index condition does not
# handle, and every other session-id predicate HogQL prints is against the bare column. `equals(...)` and the
# `has([...], col)` rewrite in clickhouse_property_resolution engage a bare-column bloom filter under default settings.
# The name stays `bloom_filter_$session_id` so the materialized-column registry (`bloom_filter_<column>`) detects it.
#
# DROP INDEX is a lightweight mutation (hardlinks each part without the index files). ClickHouse's alter sequence
# holds the ADD until that mutation finishes on each replica, so reusing the name does not race.
# No MATERIALIZE INDEX on purpose: existing parts get the index when they merge, new parts get it immediately.
DROP_EXPRESSION_BLOOM_FILTER_INDEX = "ALTER TABLE sharded_events DROP INDEX IF EXISTS `bloom_filter_$session_id`"

# 0.01 is the false-positive rate BloomFilterIndex in ee/clickhouse/materialized_columns uses for bare columns.
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
