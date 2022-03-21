from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.live_events import (
    DISTRIBUTED_LIVE_EVENTS_TABLE_SQL,
    KAFKA_LIVE_EVENTS_TABLE_SQL,
    LIVE_EVENTS_TABLE_MV_SQL,
    LIVE_EVENTS_TABLE_SQL,
    MERGE_LIVE_EVENTS_TABLE_SQL,
    WRITABLE_LIVE_EVENTS_TABLE_SQL,
)
from posthog.settings import CLICKHOUSE_REPLICATION

operations = [
    migrations.RunSQL(LIVE_EVENTS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_LIVE_EVENTS_TABLE_SQL()),
    migrations.RunSQL(LIVE_EVENTS_TABLE_MV_SQL()),
    migrations.RunSQL(MERGE_LIVE_EVENTS_TABLE_SQL()),
]

if CLICKHOUSE_REPLICATION:
    operations.extend(
        [migrations.RunSQL(WRITABLE_LIVE_EVENTS_TABLE_SQL()), migrations.RunSQL(DISTRIBUTED_LIVE_EVENTS_TABLE_SQL())]
    )
