from infi.clickhouse_orm import migrations

from posthog.performance.schema import *

operations = [
    migrations.RunSQL(PERFORMANCE_EVENTS_TABLE_SQL),
    migrations.RunSQL(KAFKA_PERFORMANCE_EVENTS_TABLE_SQL),
    migrations.RunSQL(PERFORMANCE_EVENTS_TABLE_MV_SQL),
]
