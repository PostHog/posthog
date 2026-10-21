from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_COLUMN_SHARDED_EVENTS = """
ALTER TABLE sharded_events
ADD COLUMN IF NOT EXISTS `mat_$cookieless_mode` Nullable(String)
DEFAULT JSONExtract(properties, '$cookieless_mode', 'Nullable(String)')
"""

ADD_COLUMN_EVENTS = """
ALTER TABLE events
ADD COLUMN IF NOT EXISTS `mat_$cookieless_mode` Nullable(String)
COMMENT 'column_materializer::properties::$cookieless_mode'
"""

operations = [
    run_sql_with_exceptions(
        ADD_COLUMN_SHARDED_EVENTS,
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_COLUMN_EVENTS,
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
