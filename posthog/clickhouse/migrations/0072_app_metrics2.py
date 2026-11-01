from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.app_metrics2.sql import APP_METRICS2_DATA_TABLE_SQL, DISTRIBUTED_APP_METRICS2_TABLE_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

# app_metrics2 is stored on the aux cluster and read through `app_metrics2` on the aux and data nodes.
# The Kafka consumer is on the ingestion nodes (0157 and 0227), so this migration creates no consumer.
operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS app_metrics2_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_app_metrics2 ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS app_metrics2 ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS sharded_app_metrics2 ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(APP_METRICS2_DATA_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(DISTRIBUTED_APP_METRICS2_TABLE_SQL(), node_roles=[NodeRole.AUX, NodeRole.DATA]),
]
