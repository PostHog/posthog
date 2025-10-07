from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.app_metrics2.sql import (
    APP_METRICS2_DATA_TABLE_SQL,
    APP_METRICS2_MV_TABLE_SQL,
    DISTRIBUTED_APP_METRICS2_TABLE_SQL,
    KAFKA_APP_METRICS2_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS app_metrics2_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_app_metrics2 ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS app_metrics2 ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS sharded_app_metrics2 ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(APP_METRICS2_DATA_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_APP_METRICS2_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_APP_METRICS2_TABLE_SQL()),
    run_sql_with_exceptions(APP_METRICS2_MV_TABLE_SQL()),
]
