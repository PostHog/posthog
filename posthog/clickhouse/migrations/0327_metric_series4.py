from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import METRIC_SERIES4_TABLE_SQL, METRICS2_INPUT_TO_METRIC_SERIES4_MV

operations = [
    run_sql_with_exceptions(METRIC_SERIES4_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRICS2_INPUT_TO_METRIC_SERIES4_MV(), node_roles=[NodeRole.LOGS]),
]
