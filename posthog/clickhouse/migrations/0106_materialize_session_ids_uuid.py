from infi.clickhouse_orm import migrations

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


def add_columns_to_required_tables(_):
    run_sql_with_exceptions(ADD_COLUMNS_SHARDED_EVENTS.format(table="sharded_events"))
    run_sql_with_exceptions(ADD_COLUMNS_EVENTS.format(table="events"), node_role=NodeRole.ALL)


operations = [
    migrations.RunPython(add_columns_to_required_tables),
]
