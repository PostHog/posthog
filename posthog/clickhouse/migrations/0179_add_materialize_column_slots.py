from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS, EVENTS_DATA_TABLE

operations = [
    # Only add columns to sharded_events and distributed for now (i.e. not the kafka tables / ingestion MV / writable table) to allow profiling backfill performance
    run_sql_with_exceptions(
        ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS(table=EVENTS_DATA_TABLE()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS(table="events"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
