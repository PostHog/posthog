from infi.clickhouse_orm import migrations

from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(f"DROP TABLE IF EXISTS ingestion_warnings_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE IF EXISTS kakfa_ingestion_warnings ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE IF EXISTS app_metrics_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE IF EXISTS kafka_app_metrics ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
]
