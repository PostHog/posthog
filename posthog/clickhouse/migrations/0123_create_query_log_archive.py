from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import CREATE_QUERY_LOG_ARCHIVE_TABLE

operations = [
    run_sql_with_exceptions(CREATE_QUERY_LOG_ARCHIVE_TABLE, node_role=NodeRole.ALL),
    # run_sql_with_exceptions(CREATE_QUERY_LOG_ARCHIVE_TABLE_MV, node_role=NodeRole.ALL),
]
