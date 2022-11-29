from infi.clickhouse_orm import migrations

from posthog.models.live_events.sql import (
    LIVE_EVENTS_DATA_TABLE_SQL,
    LIVE_EVENTS_MV_TABLE_SQL,
    KAFKA_LIVE_EVENTS_TABLE_SQL,
    DISTRIBUTED_LIVE_EVENTS_TABLE_SQL
)

print(LIVE_EVENTS_DATA_TABLE_SQL())

operations = [
    migrations.RunSQL(LIVE_EVENTS_DATA_TABLE_SQL()),
    migrations.RunSQL(DISTRIBUTED_LIVE_EVENTS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_LIVE_EVENTS_TABLE_SQL()),
    migrations.RunSQL(LIVE_EVENTS_MV_TABLE_SQL()),
]
