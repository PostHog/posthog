from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.traces import (
    KAFKA_TRACE_SPANS_AVRO_MV,
    KAFKA_TRACE_SPANS_AVRO_TABLE_SQL,
    TRACE_ATTRIBUTES2_TABLE_SQL,
    TRACE_ATTRIBUTES_DISTRIBUTED_TABLE_SQL,
    TRACE_ATTRIBUTES_TABLE_SQL,
    TRACE_SPAN_TO_ATTRIBUTES2_MV,
    TRACE_SPAN_TO_ATTRIBUTES_MV,
    TRACE_SPAN_TO_RESOURCE_ATTRIBUTES2_MV,
    TRACE_SPAN_TO_RESOURCE_ATTRIBUTES_MV,
    TRACE_SPAN_TO_SPAN_ATTRIBUTES2_MV,
    TRACE_SPAN_TO_SPAN_ATTRIBUTES_MV,
    TRACE_SPANS_DISTRIBUTED_TABLE_SQL,
    TRACE_SPANS_KAFKA_METRICS_TABLE_SQL,
    TRACE_SPANS_TABLE_SQL,
    TRACE_SPANS_TO_KAFKA_METRICS_MV,
)

operations = [
    run_sql_with_exceptions(TRACE_SPANS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_ATTRIBUTES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_ATTRIBUTES2_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPANS_KAFKA_METRICS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPANS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_ATTRIBUTES_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPAN_TO_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPAN_TO_RESOURCE_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPAN_TO_SPAN_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPAN_TO_ATTRIBUTES2_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPAN_TO_RESOURCE_ATTRIBUTES2_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPAN_TO_SPAN_ATTRIBUTES2_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_TRACE_SPANS_AVRO_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_TRACE_SPANS_AVRO_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(TRACE_SPANS_TO_KAFKA_METRICS_MV(), node_roles=[NodeRole.LOGS]),
]
