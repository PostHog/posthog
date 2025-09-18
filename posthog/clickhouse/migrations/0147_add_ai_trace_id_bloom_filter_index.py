from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_COLUMN_SHARDED_EVENTS = """
ALTER TABLE sharded_events
ADD COLUMN IF NOT EXISTS `mat_$ai_trace_id` Nullable(String)
MATERIALIZED JSONExtract(properties, '$ai_trace_id', 'Nullable(String)')
"""

ADD_COLUMN_EVENTS = """
ALTER TABLE events
ADD COLUMN IF NOT EXISTS `mat_$ai_trace_id` Nullable(String)
COMMENT 'column_materializer::properties::$ai_trace_id'
"""

ADD_INDEX_SHARDED_EVENTS = """
ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `bloom_filter_$ai_trace_id` `mat_$ai_trace_id`
TYPE bloom_filter(0.001)
GRANULARITY 2
"""

operations = [
    run_sql_with_exceptions(ADD_COLUMN_SHARDED_EVENTS, node_roles=[NodeRole.DATA], sharded=True),
    run_sql_with_exceptions(ADD_COLUMN_EVENTS, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(ADD_INDEX_SHARDED_EVENTS, node_roles=[NodeRole.DATA], sharded=True),
]
