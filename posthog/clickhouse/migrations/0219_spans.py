from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.traces import (
    SPANS_DISTRIBUTED_TABLE_SQL,
    SPANS_TABLE_SQL,
    TRACE_ATTRIBUTES_DISTRIBUTED_TABLE_SQL,
    TRACE_ATTRIBUTES_MV,
    TRACE_ATTRIBUTES_TABLE_SQL,
    TRACE_RESOURCE_ATTRIBUTES_MV,
)

operations = [
    run_sql_with_exceptions(
        SPANS_TABLE_SQL(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        SPANS_DISTRIBUTED_TABLE_SQL(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        TRACE_ATTRIBUTES_TABLE_SQL(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        TRACE_ATTRIBUTES_DISTRIBUTED_TABLE_SQL(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        TRACE_ATTRIBUTES_MV(),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        TRACE_RESOURCE_ATTRIBUTES_MV(),
        node_roles=[NodeRole.LOGS],
    ),
]
