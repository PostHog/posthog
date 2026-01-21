from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DIST_QUERY_LOG_ARCHIVE_MV,
    QUERY_LOG_ARCHIVE_ADD_LC_QUERY_SQL,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_MV,
    QUERY_LOG_ARCHIVE_UPDATE_MV_SQL,
    QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE,
    SHARDED_QUERY_LOG_ARCHIVE_MV,
    SHARDED_QUERY_LOG_ARCHIVE_TABLE,
    SHARDED_QUERY_LOG_ARCHIVE_WRITABLE_TABLE,
)

# US deployment: non-sharded table structure
us_operations = [
    # Add lc_query column to query_log_archive table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_LC_QUERY_SQL(QUERY_LOG_ARCHIVE_DATA_TABLE),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
        sharded=False,
    ),
    # Add lc_query column to writable_query_log_archive distributed table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_LC_QUERY_SQL(QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE),
        node_roles=[NodeRole.ENDPOINTS],
        is_alter_on_replicated_table=False,
        sharded=False,
    ),
    # Update the MV to extract lc_query from log_comment
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_UPDATE_MV_SQL(QUERY_LOG_ARCHIVE_MV),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
        is_alter_on_replicated_table=False,
        sharded=False,
    ),
]

# Non-US deployment: sharded table structure
non_us_operations = [
    # Add lc_query column to sharded_query_log_archive table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_LC_QUERY_SQL(SHARDED_QUERY_LOG_ARCHIVE_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=False,
    ),
    # Add lc_query column to writable_sharded_query_log_archive distributed table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_LC_QUERY_SQL(SHARDED_QUERY_LOG_ARCHIVE_WRITABLE_TABLE),
        node_roles=[NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
        is_alter_on_replicated_table=False,
        sharded=False,
    ),
    # Add lc_query column to query_log_archive distributed table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_LC_QUERY_SQL(QUERY_LOG_ARCHIVE_DATA_TABLE),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=False,
        sharded=False,
    ),
    # Update sharded_query_log_archive_mv on DATA nodes
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_UPDATE_MV_SQL(SHARDED_QUERY_LOG_ARCHIVE_MV),
        node_roles=[NodeRole.DATA],
        is_alter_on_replicated_table=False,
        sharded=False,
    ),
    # Update dist_query_log_archive_mv on COORDINATOR and ENDPOINTS
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_UPDATE_MV_SQL(DIST_QUERY_LOG_ARCHIVE_MV),
        node_roles=[NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
        is_alter_on_replicated_table=False,
        sharded=False,
    ),
]

operations = us_operations if settings.CLOUD_DEPLOYMENT == "US" else non_us_operations
