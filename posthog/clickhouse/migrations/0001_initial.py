from infi.clickhouse_orm import migrations

from posthog.models.event.sql import EVENTS_TABLE_SQL
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

operations = [
    migrations.RunSQL(f"CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DATABASE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(EVENTS_TABLE_SQL()),
]
