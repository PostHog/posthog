from django.conf import settings

from infi.clickhouse_orm import migrations

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import EVENTS_TABLE_JSON_MV_SQL, KAFKA_EVENTS_TABLE_JSON_SQL

ADD_COLUMNS_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER '{cluster}'
ADD COLUMN IF NOT EXISTS person_id UUID,
ADD COLUMN IF NOT EXISTS person_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group0_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group1_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group2_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group3_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group4_properties VARCHAR
"""


def add_columns_to_required_tables(_):
    sync_execute(ADD_COLUMNS_BASE_SQL.format(table="events", cluster=settings.CLICKHOUSE_CLUSTER))

    sync_execute(ADD_COLUMNS_BASE_SQL.format(table="writable_events", cluster=settings.CLICKHOUSE_CLUSTER))
    sync_execute(ADD_COLUMNS_BASE_SQL.format(table="sharded_events", cluster=settings.CLICKHOUSE_CLUSTER))


operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS events_json_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_events_json ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    migrations.RunPython(add_columns_to_required_tables),
    run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL()),
    run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL()),
]
