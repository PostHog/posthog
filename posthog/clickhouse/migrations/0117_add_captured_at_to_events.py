from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions, NodeRole
from posthog.models.event.sql import (
    EVENTS_TABLE_JSON_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
    KAFKA_EVENTS_RECENT_TABLE_JSON_SQL,
    EVENTS_RECENT_TABLE_JSON_MV_SQL,
)

ALTER_EVENTS_TABLE_ADD_CAPTURED_AT_COLUMN = """
ALTER TABLE {table_name}
    ADD COLUMN IF NOT EXISTS captured_at DateTime64(6, 'UTC')
"""

DROP_KAFKA_EVENTS_TABLE_JSON = """
    DROP TABLE IF EXISTS kafka_events_json
"""

DROP_EVENTS_TABLE_JSON_MV = """
    DROP TABLE IF EXISTS events_json_mv
"""

DROP_EVENTS_RECENT_TABLE_JSON_MV = """
    DROP TABLE IF EXISTS events_recent_json_mv
"""

DROP_KAFKA_EVENTS_RECENT_TABLE_JSON = """
    DROP TABLE IF EXISTS kafka_events_recent_json
"""


def ADD_CAPTURED_AT_COLUMNS_DISTRIBUTED_EVENTS_TABLE_SQL():
    return ALTER_EVENTS_TABLE_ADD_CAPTURED_AT_COLUMN.format(table_name="events")


def ADD_CAPTURED_AT_COLUMNS_WRITABLE_EVENTS_TABLE_SQL():
    return ALTER_EVENTS_TABLE_ADD_CAPTURED_AT_COLUMN.format(table_name="writable_events")


def ADD_CAPTURED_AT_COLUMNS_SHARDED_EVENTS_TABLE_SQL():
    return ALTER_EVENTS_TABLE_ADD_CAPTURED_AT_COLUMN.format(table_name="sharded_events")


def ADD_CAPTURED_AT_COLUMNS_EVENTS_RECENT_SQL():
    return ALTER_EVENTS_TABLE_ADD_CAPTURED_AT_COLUMN.format(table_name="events_recent")


def ADD_CAPTURED_AT_COLUMNS_DISTRIBUTED_EVENTS_RECENT_SQL():
    return ALTER_EVENTS_TABLE_ADD_CAPTURED_AT_COLUMN.format(table_name="distributed_events_recent")


operations = [
    # First drop the materialized views
    run_sql_with_exceptions(DROP_EVENTS_TABLE_JSON_MV),
    run_sql_with_exceptions(DROP_EVENTS_RECENT_TABLE_JSON_MV),
    # then drop the kafka tables
    run_sql_with_exceptions(DROP_KAFKA_EVENTS_TABLE_JSON),
    run_sql_with_exceptions(DROP_KAFKA_EVENTS_RECENT_TABLE_JSON),
    # add missing columns to all tables in the correct order
    # first the sharded tables
    run_sql_with_exceptions(ADD_CAPTURED_AT_COLUMNS_SHARDED_EVENTS_TABLE_SQL(), sharded=True),
    # second, add missing columns to writable table
    run_sql_with_exceptions(ADD_CAPTURED_AT_COLUMNS_WRITABLE_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(ADD_CAPTURED_AT_COLUMNS_EVENTS_RECENT_SQL()),
    # third, add missing columns to distributed tables
    run_sql_with_exceptions(ADD_CAPTURED_AT_COLUMNS_DISTRIBUTED_EVENTS_TABLE_SQL(), node_role=NodeRole.ALL),
    run_sql_with_exceptions(ADD_CAPTURED_AT_COLUMNS_DISTRIBUTED_EVENTS_RECENT_SQL(), node_role=NodeRole.ALL),
    # recreate the kafka tables
    run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL()),
    run_sql_with_exceptions(KAFKA_EVENTS_RECENT_TABLE_JSON_SQL()),
    # recreate the materialized views
    run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL()),
    run_sql_with_exceptions(EVENTS_RECENT_TABLE_JSON_MV_SQL()),
]
