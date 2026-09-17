from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    KAFKA_METRICS_AVRO2_MV,
    KAFKA_METRICS_AVRO2_TABLE_SQL,
    METRIC_ATTRIBUTES2_DISTRIBUTED_TABLE_SQL,
    METRIC_ATTRIBUTES2_TABLE_SQL,
    METRIC_SERIES2_DISTRIBUTED_TABLE_SQL,
    METRIC_SERIES2_TABLE_SQL,
    METRICS2_DISTRIBUTED_TABLE_SQL,
    METRICS2_INPUT_TABLE_SQL,
    METRICS2_INPUT_TO_METRIC_ATTRIBUTES_MV,
    METRICS2_INPUT_TO_METRIC_SERIES_MV,
    METRICS2_INPUT_TO_METRICS_MV,
    METRICS2_INPUT_TO_RESOURCE_ATTRIBUTES_MV,
    METRICS2_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(METRICS2_INPUT_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRIC_SERIES2_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRIC_ATTRIBUTES2_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRIC_SERIES2_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRIC_ATTRIBUTES2_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRIC_SERIES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRIC_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_RESOURCE_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO2_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_METRICS_AVRO2_MV(), node_roles=[NodeRole.LOGS]),
]
