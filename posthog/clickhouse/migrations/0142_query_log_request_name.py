from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import ADD_LC_REQUEST_NAME_SQL, QUERY_LOG_ARCHIVE_MV_V4_SQL

operations = [
    run_sql_with_exceptions(
        ADD_LC_REQUEST_NAME_SQL,
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_MV_V4_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
