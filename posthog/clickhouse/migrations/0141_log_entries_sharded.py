from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import (
    KAFKA_LOG_ENTRIES_V3_TABLE_SQL,
    LOG_ENTRIES_DISTRIBUTED_TABLE_SQL,
    LOG_ENTRIES_SHARDED_TABLE_SQL,
    LOG_ENTRIES_V3_TABLE_MV_SQL,
    LOG_ENTRIES_WRITABLE_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(LOG_ENTRIES_SHARDED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(LOG_ENTRIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(LOG_ENTRIES_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(KAFKA_LOG_ENTRIES_V3_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(LOG_ENTRIES_V3_TABLE_MV_SQL(), node_roles=[NodeRole.DATA]),
]
