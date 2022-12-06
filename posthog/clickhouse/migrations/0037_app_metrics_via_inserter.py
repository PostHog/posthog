from infi.clickhouse_orm import migrations

from posthog.models.app_metrics.sql import APP_METRICS_DATA_TABLE_SQL, DISTRIBUTED_APP_METRICS_TABLE_SQL

operations = [
    migrations.RunSQL(APP_METRICS_DATA_TABLE_SQL(table_name="sharded_app_metrics_inserter")),
    migrations.RunSQL(DISTRIBUTED_APP_METRICS_TABLE_SQL(table_name="app_metrics_inserter")),
]
