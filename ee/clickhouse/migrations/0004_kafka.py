from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.events import (
    DISTRIBUTED_EVENTS_TABLE_SQL,
    EVENTS_TABLE_MV_SQL,
    KAFKA_EVENTS_TABLE_SQL,
    WRITABLE_EVENTS_TABLE_SQL,
)
from ee.clickhouse.sql.person import (
    KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL,
    KAFKA_PERSONS_TABLE_SQL,
    PERSONS_DISTINCT_ID_TABLE_MV_SQL,
    PERSONS_TABLE_MV_SQL,
)
from posthog.settings import CLICKHOUSE_REPLICATION

operations = [
    migrations.RunSQL(KAFKA_EVENTS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_PERSONS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL()),
    migrations.RunSQL(EVENTS_TABLE_MV_SQL()),
    migrations.RunSQL(PERSONS_TABLE_MV_SQL),
    migrations.RunSQL(PERSONS_DISTINCT_ID_TABLE_MV_SQL),
]

if CLICKHOUSE_REPLICATION:
    operations.extend(
        [migrations.RunSQL(WRITABLE_EVENTS_TABLE_SQL()), migrations.RunSQL(DISTRIBUTED_EVENTS_TABLE_SQL())]
    )
