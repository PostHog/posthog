from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import (
    LOG_ATTRIBUTES_MV,
    LOG_ATTRIBUTES_TABLE_SQL,
    LOG_RESOURCE_ATTRIBUTES_MV,
    LOGS32_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        LOGS32_TABLE_SQL,
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        LOG_ATTRIBUTES_TABLE_SQL,
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        LOG_ATTRIBUTES_MV,
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        LOG_RESOURCE_ATTRIBUTES_MV,
        node_roles=[NodeRole.LOGS],
    ),
]
