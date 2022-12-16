from infi.clickhouse_orm import migrations

from posthog import settings
from posthog.performance.sql import (
    DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL,
    KAFKA_PERFORMANCE_EVENTS_TABLE_SQL,
    PERFORMANCE_EVENTS_TABLE_MV_SQL,
    PERFORMANCE_EVENTS_TABLE_SQL,
    WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL,
)

operations = [
    migrations.RunSQL(PERFORMANCE_EVENTS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_PERFORMANCE_EVENTS_TABLE_SQL()),
    migrations.RunSQL(PERFORMANCE_EVENTS_TABLE_MV_SQL()),
]

if settings.CLICKHOUSE_REPLICATION:
    operations = [
        migrations.RunSQL(WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL()),
        migrations.RunSQL(DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL()),
    ] + operations
