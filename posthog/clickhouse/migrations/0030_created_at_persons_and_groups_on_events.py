from infi.clickhouse_orm import migrations

from posthog.clickhouse.replication.utils import clickhouse_is_replicated
from posthog.client import sync_execute
from posthog.models.event.sql import EVENTS_TABLE_JSON_MV_SQL, KAFKA_EVENTS_TABLE_JSON_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

ADD_COLUMNS_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER '{cluster}'
ADD COLUMN IF NOT EXISTS person_created_at DateTime64,
ADD COLUMN IF NOT EXISTS group0_created_at DateTime64,
ADD COLUMN IF NOT EXISTS group1_created_at DateTime64,
ADD COLUMN IF NOT EXISTS group2_created_at DateTime64,
ADD COLUMN IF NOT EXISTS group3_created_at DateTime64,
ADD COLUMN IF NOT EXISTS group4_created_at DateTime64
"""


def add_columns_to_required_tables(_):
    sync_execute(ADD_COLUMNS_BASE_SQL.format(table="events", cluster=CLICKHOUSE_CLUSTER))

    if clickhouse_is_replicated():
        sync_execute(ADD_COLUMNS_BASE_SQL.format(table="writable_events", cluster=CLICKHOUSE_CLUSTER))
        sync_execute(ADD_COLUMNS_BASE_SQL.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))


operations = [
    migrations.RunSQL(f"DROP TABLE IF EXISTS events_json_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE IF EXISTS kafka_events_json ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunPython(add_columns_to_required_tables),
    migrations.RunSQL(KAFKA_EVENTS_TABLE_JSON_SQL()),
    migrations.RunSQL(EVENTS_TABLE_JSON_MV_SQL()),
]
