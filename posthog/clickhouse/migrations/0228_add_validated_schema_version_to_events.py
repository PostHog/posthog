import re

from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.models.event.sql import EVENTS_TABLE_JSON_MV_SQL, KAFKA_EVENTS_TABLE_JSON_SQL

ALTER_EVENTS_TABLE_ADD_COLUMN = """
ALTER TABLE {table_name}
    ADD COLUMN IF NOT EXISTS validated_schema_version Int32 DEFAULT 0
"""

DROP_KAFKA_EVENTS_TABLE_JSON = """
    DROP TABLE IF EXISTS kafka_events_json
"""

DROP_EVENTS_TABLE_JSON_MV = """
    DROP TABLE IF EXISTS events_json_mv
"""


def _strip_on_cluster(sql: str) -> str:
    return re.sub(r"\s*ON CLUSTER '[^']*'", "", sql)


operations = [
    # First drop the materialized view
    run_sql_with_exceptions(DROP_EVENTS_TABLE_JSON_MV),
    # Then drop the kafka table
    run_sql_with_exceptions(DROP_KAFKA_EVENTS_TABLE_JSON),
    # Add column to sharded_events (replicated, one per shard)
    run_sql_with_exceptions(
        ALTER_EVENTS_TABLE_ADD_COLUMN.format(table_name="sharded_events"),
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # Add column to writable_events (distributed write table)
    run_sql_with_exceptions(
        ALTER_EVENTS_TABLE_ADD_COLUMN.format(table_name="writable_events"),
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # Add column to events (distributed read table, all nodes)
    run_sql_with_exceptions(
        ALTER_EVENTS_TABLE_ADD_COLUMN.format(table_name="events"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # Recreate the kafka table (without ON CLUSTER, migration framework handles distribution)
    run_sql_with_exceptions(_strip_on_cluster(KAFKA_EVENTS_TABLE_JSON_SQL())),
    # Recreate the materialized view
    run_sql_with_exceptions(_strip_on_cluster(EVENTS_TABLE_JSON_MV_SQL())),
]
