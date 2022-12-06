from django.conf import settings
from infi.clickhouse_orm import migrations

operations = [
    # First we remove the Materialized View table and the KafkaTable
    migrations.RunSQL(
        f"DROP TABLE IF EXISTS `{settings.CLICKHOUSE_DATABASE}.app_metrics_mv` ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' SYNC"
    ),
    migrations.RunSQL(
        f"DROP TABLE IF EXISTS `{settings.CLICKHOUSE_CLUSTER}.kafka_app_metrics` ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' SYNC"
    ),
]
