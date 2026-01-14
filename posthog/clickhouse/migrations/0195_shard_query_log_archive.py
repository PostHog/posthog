from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DISTRIBUTED_QUERY_LOG_ARCHIVE_TABLE_SQL,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_MV,
    QUERY_LOG_ARCHIVE_NEW_MV_SQL,
    QUERY_LOG_ARCHIVE_OLD_TABLE,
    QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE,
    SHARDED_QUERY_LOG_ARCHIVE_TABLE,
    SHARDED_QUERY_LOG_ARCHIVE_TABLE_SQL,
    SHARDED_WRITABLE_QUERY_LOG_ARCHIVE_TABLE_SQL,
)

operations = [
    # 1. Create new sharded data table on DATA nodes (no disruption to existing flow)
    run_sql_with_exceptions(
        SHARDED_QUERY_LOG_ARCHIVE_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # 2. Update MV on DATA nodes to write directly to sharded table
    #    Drop and recreate - minimal gap between operations
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {QUERY_LOG_ARCHIVE_MV}",
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_NEW_MV_SQL(
            view_name=QUERY_LOG_ARCHIVE_MV,
            dest_table=SHARDED_QUERY_LOG_ARCHIVE_TABLE,
        ),
        node_roles=[NodeRole.DATA],
    ),
    # 3. Drop MV on COORDINATOR and ENDPOINTS
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {QUERY_LOG_ARCHIVE_MV}",
        node_roles=[NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE}",
        node_roles=[NodeRole.ENDPOINTS],
    ),
    # 5. Create distributed table (query_log_archive_v2) for querying
    run_sql_with_exceptions(
        DISTRIBUTED_QUERY_LOG_ARCHIVE_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # 6. Create writable distributed table on COORDINATOR
    run_sql_with_exceptions(
        SHARDED_WRITABLE_QUERY_LOG_ARCHIVE_TABLE_SQL(),
        node_roles=[NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
    ),
    # 7. Recreate MV on COORDINATOR to write through writable distributed table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_NEW_MV_SQL(
            view_name=QUERY_LOG_ARCHIVE_MV,
            dest_table=QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE,
        ),
        node_roles=[NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
    ),
    # 4. Rename old replicated table to preserve historical data
    run_sql_with_exceptions(
        f"RENAME TABLE {QUERY_LOG_ARCHIVE_DATA_TABLE} TO {QUERY_LOG_ARCHIVE_OLD_TABLE}",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
