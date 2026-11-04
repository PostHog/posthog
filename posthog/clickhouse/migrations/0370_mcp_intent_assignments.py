from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.mcp_analytics.backend.facade.clickhouse_schema import (
    MCP_INTENT_ASSIGNMENTS_DATA_TABLE_SQL,
    MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE_SQL,
    MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE_SQL,
)

# Main cluster, sharded, like the document embedding tables the pipeline reads from (0191).
operations = [
    run_sql_with_exceptions(
        MCP_INTENT_ASSIGNMENTS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
    run_sql_with_exceptions(
        MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
