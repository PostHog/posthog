from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_MV,
    QUERY_LOG_ARCHIVE_NEW_MV_SQL,
    QUERY_LOG_ARCHIVE_NEW_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_NEW_TABLE_SQL(table_name=QUERY_LOG_ARCHIVE_DATA_TABLE),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_NEW_MV_SQL(view_name=QUERY_LOG_ARCHIVE_MV, dest_table=QUERY_LOG_ARCHIVE_DATA_TABLE),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
