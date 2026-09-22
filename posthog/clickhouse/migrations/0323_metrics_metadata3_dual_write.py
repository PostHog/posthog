from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    METRIC_ATTRIBUTES3_TABLE_SQL,
    METRIC_NAMES3_TABLE_SQL,
    METRIC_SERIES3_TABLE_SQL,
    METRICS2_INPUT_TO_METRIC_ATTRIBUTES3_MV,
    METRICS2_INPUT_TO_METRIC_NAMES3_MV,
    METRICS2_INPUT_TO_METRIC_SERIES3_MV,
    METRICS2_INPUT_TO_RESOURCE_ATTRIBUTES3_MV,
)

operations = [
    run_sql_with_exceptions(METRIC_SERIES3_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRIC_ATTRIBUTES3_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRIC_NAMES3_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRIC_SERIES3_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRIC_ATTRIBUTES3_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_RESOURCE_ATTRIBUTES3_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRIC_NAMES3_MV(), node_roles=[NodeRole.LOGS]),
]
