from infi.clickhouse_orm import migrations

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import EVENTS_TABLE_JSON_MV_SQL, KAFKA_EVENTS_TABLE_JSON_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

# verified field: 0 = not_verified (default), 1 = verified, 2 = invalid
# UInt8 defaults to 0, which is "not_verified" as desired
ADD_VERIFIED_COLUMN_SQL = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS verified UInt8
"""


def add_verified_column_to_tables(_):
    # Add to distributed/proxy table (non-sharded, replicated)
    sync_execute(ADD_VERIFIED_COLUMN_SQL.format(table="events", cluster=CLICKHOUSE_CLUSTER))

    # Add to writable table (non-sharded, replicated)
    sync_execute(ADD_VERIFIED_COLUMN_SQL.format(table="writable_events", cluster=CLICKHOUSE_CLUSTER))

    # Add to sharded events table (sharded, replicated)
    sync_execute(ADD_VERIFIED_COLUMN_SQL.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))


operations = [
    # Drop existing Kafka tables and materialized views
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS events_json_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_events_json ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    # Add verified column to all event tables
    migrations.RunPython(add_verified_column_to_tables),
    # Recreate Kafka tables and materialized views with verified column
    run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL()),
    run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL()),
]
