from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.app_metrics.sql import (
    APP_METRICS_DATA_TABLE_SQL,
    APP_METRICS_MV_TABLE_SQL,
    APP_METRICS_SHARDED_TABLE,
    DISTRIBUTED_APP_METRICS_TABLE_SQL,
    KAFKA_APP_METRICS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(APP_METRICS_DATA_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(DISTRIBUTED_APP_METRICS_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(KAFKA_APP_METRICS_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(APP_METRICS_MV_TABLE_SQL(target_table=APP_METRICS_SHARDED_TABLE), node_roles=NodeRole.DATA),
]
