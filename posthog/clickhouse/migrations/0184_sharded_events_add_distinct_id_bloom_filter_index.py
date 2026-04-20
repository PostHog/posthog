from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_BLOOM_FILTER_INDEX_SHARDED_EVENTS = """
ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS bloom_filter_distinct_id distinct_id
TYPE bloom_filter
GRANULARITY 1
"""

operations = [
    run_sql_with_exceptions(
        ADD_BLOOM_FILTER_INDEX_SHARDED_EVENTS,
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
