from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DIST_QUERY_LOG_ARCHIVE_MV,
    MV_SELECT_SQL,
    QUERY_LOG_ARCHIVE_ADD_V8_COLUMNS_SQL,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    SHARDED_QUERY_LOG_ARCHIVE_MV,
    SHARDED_QUERY_LOG_ARCHIVE_TABLE,
    SHARDED_QUERY_LOG_ARCHIVE_WRITABLE_TABLE,
    SHARDED_WRITABLE_QUERY_LOG_ARCHIVE_TABLE_SQL,
)

operations = [
    # Add columns to the sharded data table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_V8_COLUMNS_SQL(SHARDED_QUERY_LOG_ARCHIVE_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        SHARDED_WRITABLE_QUERY_LOG_ARCHIVE_TABLE_SQL(),
        node_roles=[NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
    ),
    # Add columns to the writable distributed table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_V8_COLUMNS_SQL(SHARDED_QUERY_LOG_ARCHIVE_WRITABLE_TABLE),
        node_roles=[NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # Add columns to the distributed read table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_V8_COLUMNS_SQL(QUERY_LOG_ARCHIVE_DATA_TABLE),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # Update the MV on data nodes
    run_sql_with_exceptions(
        f"ALTER TABLE {SHARDED_QUERY_LOG_ARCHIVE_MV} MODIFY QUERY\n{MV_SELECT_SQL}",
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # Update the MV on coordinator/endpoints nodes
    run_sql_with_exceptions(
        f"ALTER TABLE {DIST_QUERY_LOG_ARCHIVE_MV} MODIFY QUERY\n{MV_SELECT_SQL}",
        node_roles=[NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
