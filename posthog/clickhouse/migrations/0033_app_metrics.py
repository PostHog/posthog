from infi.clickhouse_orm import migrations

from posthog.models.app_metrics.sql import (
    APP_METRICS_DATA_TABLE_SQL,
    APP_METRICS_MV_TABLE_SQL,
    DISTRIBUTED_APP_METRICS_TABLE_SQL,
    KAFKA_APP_METRICS_TABLE_SQL,
)

operations = [
    migrations.RunSQL(APP_METRICS_DATA_TABLE_SQL()),
    migrations.RunSQL(DISTRIBUTED_APP_METRICS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_APP_METRICS_TABLE_SQL()),
    migrations.RunSQL(APP_METRICS_MV_TABLE_SQL()),
]
