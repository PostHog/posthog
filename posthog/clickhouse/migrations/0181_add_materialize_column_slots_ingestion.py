from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS,
    EVENTS_TABLE_JSON_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
    WRITABLE_EVENTS_DATA_TABLE,
)

DROP_EVENTS_TABLE_JSON_MV = """
    DROP TABLE IF EXISTS events_json_mv SYNC;
"""

DROP_KAFKA_EVENTS_TABLE = """
    DROP TABLE IF EXISTS kafka_events_json SYNC;
"""

# See when these were added to the sharded / distributed tables in 0179

operations = [
    # writeable table
    run_sql_with_exceptions(
        ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS(table=WRITABLE_EVENTS_DATA_TABLE()),
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # drop events mv
    run_sql_with_exceptions(
        DROP_EVENTS_TABLE_JSON_MV,
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # drop kafka table
    run_sql_with_exceptions(
        DROP_KAFKA_EVENTS_TABLE,
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # recreate kafka table
    run_sql_with_exceptions(
        KAFKA_EVENTS_TABLE_JSON_SQL(),
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # recreate events MV
    run_sql_with_exceptions(
        EVENTS_TABLE_JSON_MV_SQL(),
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
