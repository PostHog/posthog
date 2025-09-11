from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.models.event.sql import EVENTS_TABLE_JSON_MV_SQL, KAFKA_EVENTS_TABLE_JSON_SQL

ALTER_EVENTS_TABLE_ADD_BREADCRUMBS_COLUMN = """
ALTER TABLE {table_name}
    ADD COLUMN IF NOT EXISTS consumer_breadcrumbs Array(String)
"""

DROP_KAFKA_EVENTS_TABLE_JSON = """
    DROP TABLE IF EXISTS kafka_events_json
"""

DROP_EVENTS_TABLE_JSON_MV = """
    DROP TABLE IF EXISTS events_json_mv
"""


def ADD_BREADCRUMBS_COLUMNS_DISTRIBUTED_EVENTS_TABLE_SQL():
    return ALTER_EVENTS_TABLE_ADD_BREADCRUMBS_COLUMN.format(table_name="events")


def ADD_BREADCRUMBS_COLUMNS_WRITABLE_EVENTS_TABLE_SQL():
    return ALTER_EVENTS_TABLE_ADD_BREADCRUMBS_COLUMN.format(table_name="writable_events")


def ADD_BREADCRUMBS_COLUMNS_SHARDED_EVENTS_TABLE_SQL():
    return ALTER_EVENTS_TABLE_ADD_BREADCRUMBS_COLUMN.format(table_name="sharded_events")


operations = [
    # First drop the materialized view
    run_sql_with_exceptions(DROP_EVENTS_TABLE_JSON_MV),
    # then drop the kafka table
    run_sql_with_exceptions(DROP_KAFKA_EVENTS_TABLE_JSON),
    # add missing columns to all tables in correct order
    # first the sharded tables
    run_sql_with_exceptions(ADD_BREADCRUMBS_COLUMNS_SHARDED_EVENTS_TABLE_SQL(), sharded=True),
    # second, add missing columns to writable table
    run_sql_with_exceptions(ADD_BREADCRUMBS_COLUMNS_WRITABLE_EVENTS_TABLE_SQL()),
    # third,add missing columns to distributed table
    run_sql_with_exceptions(
        ADD_BREADCRUMBS_COLUMNS_DISTRIBUTED_EVENTS_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    # recreate the kafka table
    run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL()),
    # recreate the materialized view
    run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL()),
]
