from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_COLUMNS_SHARDED_EVENTS = """
ALTER TABLE {table}
ADD COLUMN IF NOT EXISTS $session_id_uuid Nullable(UInt128) MATERIALIZED toUInt128(JSONExtract(properties, '$session_id', 'Nullable(UUID)'))
"""

ADD_COLUMNS_EVENTS = """
ALTER TABLE {table}
ADD COLUMN IF NOT EXISTS $session_id_uuid Nullable(UInt128)
"""


operations = [
    run_sql_with_exceptions(ADD_COLUMNS_SHARDED_EVENTS.format(table="sharded_events"), sharded=True),
    run_sql_with_exceptions(
        ADD_COLUMNS_EVENTS.format(table="events"), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
]
