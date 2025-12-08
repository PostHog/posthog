from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_COLUMN_SHARDED_EVENTS = """
ALTER TABLE sharded_events
ADD COLUMN IF NOT EXISTS `mat_$ai_session_id` Nullable(String)
MATERIALIZED JSONExtract(properties, '$ai_session_id', 'Nullable(String)')
"""

ADD_COLUMN_EVENTS = """
ALTER TABLE events
ADD COLUMN IF NOT EXISTS `mat_$ai_session_id` Nullable(String)
COMMENT 'column_materializer::properties::$ai_session_id'
"""

ADD_BLOOM_FILTER_INDEX_SHARDED_EVENTS = """
ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `bloom_filter_$ai_session_id` `mat_$ai_session_id`
TYPE bloom_filter
GRANULARITY 1
"""

ADD_MINMAX_INDEX_SHARDED_EVENTS = """
ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `minmax_$ai_session_id` `mat_$ai_session_id`
TYPE minmax
GRANULARITY 1
"""

operations = [
    run_sql_with_exceptions(
        ADD_COLUMN_SHARDED_EVENTS, node_roles=[NodeRole.DATA], sharded=True, is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        ADD_COLUMN_EVENTS,
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_BLOOM_FILTER_INDEX_SHARDED_EVENTS,
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_MINMAX_INDEX_SHARDED_EVENTS, node_roles=[NodeRole.DATA], sharded=True, is_alter_on_replicated_table=True
    ),
]
