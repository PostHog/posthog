from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS,
    EVENTS_TABLE_JSON_MV_SQL,
    WRITABLE_EVENTS_DATA_TABLE,
)

DETACH_KAFKA = """
    DETACH TABLE IF EXISTS kafka_events_json;
"""

ATTACH_KAFKA = """
    ATTACH TABLE IF EXISTS kafka_events_json;
"""

DROP_EVENTS_JSON_MV = """
    DROP TABLE IF EXISTS events_json_mv SYNC;
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
    # kafka table
    run_sql_with_exceptions(
        ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS(table="kafka_events_json"),
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # pause ingestion from the kafka tables
    run_sql_with_exceptions(
        DETACH_KAFKA, node_roles=[NodeRole.INGESTION_EVENTS], sharded=False, is_alter_on_replicated_table=False
    ),
    # drop MV
    run_sql_with_exceptions(
        DROP_EVENTS_JSON_MV,
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # recreate MV
    run_sql_with_exceptions(
        EVENTS_TABLE_JSON_MV_SQL(),
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # resume ingestion
    run_sql_with_exceptions(ATTACH_KAFKA, node_roles=[NodeRole.INGESTION_EVENTS]),
]
