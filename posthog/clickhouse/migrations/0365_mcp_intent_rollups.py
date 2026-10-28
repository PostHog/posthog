from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.mcp_analytics.backend.facade.clickhouse_schema import (
    ADD_TOOL_COLUMN_TO_ASSIGNMENTS_SQL,
    MCP_INTENT_ASSIGNMENTS_DATA_TABLE,
    MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
    MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE,
    MCP_INTENT_CALLS_HOURLY_DATA_TABLE_SQL,
    MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE_SQL,
    MCP_INTENT_CALLS_HOURLY_WRITABLE_TABLE_SQL,
    MCP_INTENT_TOPIC_DAILY_DATA_TABLE_SQL,
    MCP_INTENT_TOPIC_DAILY_DISTRIBUTED_TABLE_SQL,
    MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE_SQL,
)

# Rollups for the intent topic queries, plus the tool column on the assignments table.
operations = [
    run_sql_with_exceptions(
        ADD_TOOL_COLUMN_TO_ASSIGNMENTS_SQL(MCP_INTENT_ASSIGNMENTS_DATA_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_TOOL_COLUMN_TO_ASSIGNMENTS_SQL(MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_TOOL_COLUMN_TO_ASSIGNMENTS_SQL(MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]

for data_sql, distributed_sql, writable_sql in (
    (
        MCP_INTENT_CALLS_HOURLY_DATA_TABLE_SQL,
        MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE_SQL,
        MCP_INTENT_CALLS_HOURLY_WRITABLE_TABLE_SQL,
    ),
    (
        MCP_INTENT_TOPIC_DAILY_DATA_TABLE_SQL,
        MCP_INTENT_TOPIC_DAILY_DISTRIBUTED_TABLE_SQL,
        MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE_SQL,
    ),
):
    operations.extend(
        [
            run_sql_with_exceptions(data_sql(), node_roles=[NodeRole.DATA], sharded=True),
            run_sql_with_exceptions(distributed_sql(), node_roles=[NodeRole.DATA]),
            run_sql_with_exceptions(writable_sql(), node_roles=[NodeRole.DATA]),
        ]
    )
