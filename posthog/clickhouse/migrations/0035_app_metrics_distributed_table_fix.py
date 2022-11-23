from infi.clickhouse_orm import migrations

from posthog.models.app_metrics.sql import (
    APP_METRICS_MV_TABLE_SQL,
    DISTRIBUTED_APP_METRICS_TABLE_SQL,
    KAFKA_APP_METRICS_TABLE_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(f"DROP TABLE IF EXISTS app_metrics_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE IF EXISTS kafka_app_metrics ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE IF EXISTS app_metrics ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(DISTRIBUTED_APP_METRICS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_APP_METRICS_TABLE_SQL()),
    migrations.RunSQL(APP_METRICS_MV_TABLE_SQL()),
]
