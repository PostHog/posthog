from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    METRIC_ATTRIBUTES_MV,
    METRIC_ATTRIBUTES_TABLE_SQL,
    METRIC_RESOURCE_ATTRIBUTES_MV,
    METRICS1_TABLE_SQL,
    METRICS_DISTRIBUTED_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        METRICS1_TABLE_SQL(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        METRICS_DISTRIBUTED_TABLE_SQL(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        METRIC_ATTRIBUTES_TABLE_SQL(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        METRIC_ATTRIBUTES_MV(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        METRIC_RESOURCE_ATTRIBUTES_MV(),
        node_roles=[NodeRole.LOGS],
    ),
]
