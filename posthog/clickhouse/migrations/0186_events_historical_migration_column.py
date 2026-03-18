from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_HISTORICAL_MIGRATION_COLUMN_EVENTS = """
ALTER TABLE {table}
ADD COLUMN IF NOT EXISTS historical_migration Bool
"""

ADD_HISTORICAL_MIGRATION_COLUMN_INDEX = """
ALTER TABLE {table}
ADD INDEX IF NOT EXISTS minmax_historical_migration (historical_migration) TYPE minmax GRANULARITY 1
"""

operations = [
    run_sql_with_exceptions(
        ADD_HISTORICAL_MIGRATION_COLUMN_EVENTS.format(table="sharded_events"),
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
        ADD_HISTORICAL_MIGRATION_COLUMN_EVENTS.format(table="events"),
        node_roles=[NodeRole.COORDINATOR, NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
