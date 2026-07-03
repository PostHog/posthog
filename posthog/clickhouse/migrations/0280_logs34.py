from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import (
    KAFKA_LOGS34_AVRO_MV,
    KAFKA_LOGS_AVRO_BILLING_METRICS_MV,
    KAFKA_LOGS_AVRO_KAFKA_METRICS_MV,
    KAFKA_LOGS_AVRO_TABLE_SQL,
    LOG_ATTRIBUTES2_DISTRIBUTED_TABLE_SQL,
    LOG_ATTRIBUTES2_TABLE_SQL,
    LOGS34_DISTRIBUTED_TABLE_SQL,
    LOGS34_TABLE_SQL,
    LOGS34_TO_LOG_ATTRIBUTES_MV,
    LOGS34_TO_RESOURCE_ATTRIBUTES_MV,
    LOGS_BILLING_METRICS_DISTRIBUTED_TABLE_SQL,
    LOGS_BILLING_METRICS_TABLE_SQL,
    LOGS_KAFKA_METRICS_DISTRIBUTED_TABLE_SQL,
    LOGS_KAFKA_METRICS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(LOGS34_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOG_ATTRIBUTES2_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_BILLING_METRICS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_KAFKA_METRICS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS34_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOG_ATTRIBUTES2_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_BILLING_METRICS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_KAFKA_METRICS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS34_TO_LOG_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS34_TO_RESOURCE_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_LOGS_AVRO_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_LOGS34_AVRO_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_LOGS_AVRO_KAFKA_METRICS_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_LOGS_AVRO_BILLING_METRICS_MV(), node_roles=[NodeRole.LOGS]),
]
