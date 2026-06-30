from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_OPS_MV,
    QUERY_LOG_ARCHIVE_OPS_MV_SQL,
    WRITABLE_QUERY_LOG_ARCHIVE_TABLE,
)

# Same fan-out as the MV's creating migration (0273): the slim MV runs on every
# cluster, copying that cluster's system.query_log into writable_query_log_archive.
ALL_ROLES = [
    NodeRole.DATA,
    NodeRole.ENDPOINTS,
    NodeRole.AUX,
    NodeRole.AI_EVENTS,
    NodeRole.SESSIONS,
    NodeRole.OPS,
]

# Wrap log_comment in if(isValidJSON(...), ..., '{}') so a non-JSON log_comment
# can't break the JSON column in writable_query_log_archive. Recreate the MV to
# converge clusters still on the unguarded definition.
operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {QUERY_LOG_ARCHIVE_OPS_MV}", node_roles=ALL_ROLES),
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_OPS_MV_SQL(view_name=QUERY_LOG_ARCHIVE_OPS_MV, dest_table=WRITABLE_QUERY_LOG_ARCHIVE_TABLE),
        node_roles=ALL_ROLES,
    ),
]
