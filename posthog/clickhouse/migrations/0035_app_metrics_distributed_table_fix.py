from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.app_metrics.sql import (
    APP_METRICS_MV_TABLE_SQL,
    DISTRIBUTED_APP_METRICS_TABLE_SQL,
    KAFKA_APP_METRICS_TABLE_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS app_metrics_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_app_metrics ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS app_metrics ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(DISTRIBUTED_APP_METRICS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_APP_METRICS_TABLE_SQL()),
    run_sql_with_exceptions(APP_METRICS_MV_TABLE_SQL()),
]
