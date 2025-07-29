from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_TABLE_SQL,
    QUERY_LOG_ARCHIVE_MV,
)

operations = [
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_TABLE_SQL(on_cluster=False), node_role=NodeRole.ALL),
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_MV(on_cluster=False), node_role=NodeRole.ALL),
]
