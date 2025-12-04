from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_HISTORICAL_MIGRATION_COLUMN_SHARDED_EVENTS = """
ALTER TABLE {table}
ADD COLUMN IF NOT EXISTS historical_migration Bool
"""

ADD_HISTORICAL_MIGRATION_COLUMN_INDEX = """
ALTER TABLE {table}
ADD INDEX IF NOT EXISTS historical_migration_set (historical_migration) TYPE set(7) GRANULARITY 1
"""

operations = [
    run_sql_with_exceptions(
        ADD_HISTORICAL_MIGRATION_COLUMN_SHARDED_EVENTS.format(table="sharded_events"),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_HISTORICAL_MIGRATION_COLUMN_INDEX.format(table="sharded_events"),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_HISTORICAL_MIGRATION_COLUMN_INDEX.format(table="events"),
        node_roles=[NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
