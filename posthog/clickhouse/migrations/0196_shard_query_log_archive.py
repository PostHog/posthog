from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DIST_QUERY_LOG_ARCHIVE_MV,
    DISTRIBUTED_QUERY_LOG_ARCHIVE_TABLE_SQL,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_MV,
    QUERY_LOG_ARCHIVE_NEW_MV_SQL,
    QUERY_LOG_ARCHIVE_OLD_TABLE,
    QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE,
    SHARDED_QUERY_LOG_ARCHIVE_MV,
    SHARDED_QUERY_LOG_ARCHIVE_TABLE,
    SHARDED_QUERY_LOG_ARCHIVE_TABLE_SQL,
    SHARDED_QUERY_LOG_ARCHIVE_WRITABLE_TABLE,
    SHARDED_WRITABLE_QUERY_LOG_ARCHIVE_TABLE_SQL,
)

operations = (
    [
        # create sharded data table
        run_sql_with_exceptions(
            SHARDED_QUERY_LOG_ARCHIVE_TABLE_SQL(),
            node_roles=[NodeRole.DATA],
        ),
        # start writing query log to it on workers
        run_sql_with_exceptions(
            QUERY_LOG_ARCHIVE_NEW_MV_SQL(
                view_name=SHARDED_QUERY_LOG_ARCHIVE_MV,
                dest_table=SHARDED_QUERY_LOG_ARCHIVE_TABLE,
            ),
            node_roles=[NodeRole.DATA],
        ),
        # and add writable view, so other nodes can write to it
        run_sql_with_exceptions(
            SHARDED_WRITABLE_QUERY_LOG_ARCHIVE_TABLE_SQL(),
            node_roles=[NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
        ),
        # This is tricky part, the worker nodes, writes to own replica of sharded_query_log_archive.
        # This limits the parts flying in the cluster. But coordinator does not have own query_log_archive table,
        # therefor needs to write to distributed one. This will need to be carried through all query_log_archive updates!
        run_sql_with_exceptions(
            QUERY_LOG_ARCHIVE_NEW_MV_SQL(
                view_name=DIST_QUERY_LOG_ARCHIVE_MV,
                dest_table=SHARDED_QUERY_LOG_ARCHIVE_WRITABLE_TABLE,
            ),
            node_roles=[NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
        ),
        # Drop old MV
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {QUERY_LOG_ARCHIVE_MV}",
            node_roles=[NodeRole.DATA, NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
        ),
        # and drop old distributed table for endpoints
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE}",
            node_roles=[NodeRole.ENDPOINTS],
        ),
        # rename old table, so it can be taken care later
        run_sql_with_exceptions(
            f"RENAME TABLE {QUERY_LOG_ARCHIVE_DATA_TABLE} TO {QUERY_LOG_ARCHIVE_OLD_TABLE}",
            node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        ),
        # and create a new distributed so we can query it without interruptions
        run_sql_with_exceptions(
            DISTRIBUTED_QUERY_LOG_ARCHIVE_TABLE_SQL(),
            node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        ),
    ]
    if settings.CLOUD_DEPLOYMENT != "US"
    else []
)
