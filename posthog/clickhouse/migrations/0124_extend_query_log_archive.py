from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    MODIFY_QUERY_LOG_ARCHIVE_TABLE_V2,
    QUERY_LOG_ARCHIVE_MV_V2,
)

operations = [
    run_sql_with_exceptions(q, node_role=NodeRole.ALL, is_alter_on_replicated_table=True)
    for q in MODIFY_QUERY_LOG_ARCHIVE_TABLE_V2
] + [run_sql_with_exceptions(QUERY_LOG_ARCHIVE_MV_V2(on_cluster=False), node_role=NodeRole.ALL)]
