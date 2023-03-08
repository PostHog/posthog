from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.app_metrics.sql import (
    APP_METRICS_DATA_TABLE_SQL,
    APP_METRICS_MV_TABLE_SQL,
    DISTRIBUTED_APP_METRICS_TABLE_SQL,
    KAFKA_APP_METRICS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(APP_METRICS_DATA_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_APP_METRICS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_APP_METRICS_TABLE_SQL()),
    run_sql_with_exceptions(APP_METRICS_MV_TABLE_SQL()),
]
