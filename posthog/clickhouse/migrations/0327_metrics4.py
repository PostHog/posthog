from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    METRICS2_INPUT_TO_METRICS4_ATTRIBUTES_MV,
    METRICS2_INPUT_TO_METRICS4_NAMES_MV,
    METRICS2_INPUT_TO_METRICS4_RESOURCE_ATTRIBUTES_MV,
    METRICS2_INPUT_TO_METRICS4_SAMPLES_MV,
    METRICS2_INPUT_TO_METRICS4_SERIES_MV,
    METRICS4_ATTRIBUTES_TABLE_SQL,
    METRICS4_NAMES_TABLE_SQL,
    METRICS4_SAMPLES_TABLE_SQL,
    METRICS4_SERIES_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(METRICS4_SAMPLES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS4_SERIES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS4_NAMES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS4_ATTRIBUTES_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS4_SAMPLES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS4_SERIES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS4_NAMES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS4_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRICS4_RESOURCE_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
]
