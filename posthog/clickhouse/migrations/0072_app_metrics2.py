from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.app_metrics2.sql import (
    APP_METRICS2_DATA_TABLE_SQL,
    APP_METRICS2_MV_TABLE_SQL,
    APP_METRICS2_SHARDED_TABLE,
    DISTRIBUTED_APP_METRICS2_TABLE_SQL,
    KAFKA_APP_METRICS2_TABLE_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS app_metrics2_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_app_metrics2 ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS app_metrics2 ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS sharded_app_metrics2 ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(APP_METRICS2_DATA_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_APP_METRICS2_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_APP_METRICS2_TABLE_SQL()),
    run_sql_with_exceptions(APP_METRICS2_MV_TABLE_SQL(target_table=APP_METRICS2_SHARDED_TABLE)),
]
