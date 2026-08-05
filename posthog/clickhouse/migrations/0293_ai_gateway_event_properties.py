from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.events_json import (
    DISTRIBUTED_EVENTS_JSON_TABLE,
    EVENTS_JSON_DATA_TABLE,
    WRITABLE_EVENTS_JSON_TABLE,
)
from posthog.models.event.sql import EVENTS_PROPERTIES_JSON_TYPE


def modify_properties_column(table: str) -> str:
    return f"ALTER TABLE {table} MODIFY COLUMN IF EXISTS properties {EVENTS_PROPERTIES_JSON_TYPE()}"


operations = [
    run_sql_with_exceptions(
        modify_properties_column(EVENTS_JSON_DATA_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        modify_properties_column(WRITABLE_EVENTS_JSON_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        modify_properties_column(DISTRIBUTED_EVENTS_JSON_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        modify_properties_column(WRITABLE_EVENTS_JSON_TABLE),
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
