from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    MV_SELECT_SQL_V3,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE,
    QUERY_LOG_ARCHIVE_V3_MV,
    SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE,
    WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE,
)
from posthog.run_mode import run_mode

# ALTER TABLE has no IF EXISTS guard, so a role whose nodes lack the table aborts the migration.
# Migration 0273 creates the writable table and the MV on these roles, and the read table on every node.
LOCAL_WRITE_PATH_ROLES = [
    NodeRole.DATA,
    NodeRole.ENDPOINTS,
    NodeRole.AUX,
    NodeRole.AI_EVENTS,
    NodeRole.SESSIONS,
    NodeRole.OPS,
]
# The cloud archive was built by hand, and the cloud HCL goldens record it: logs, apm and batch_exports
# also run the writable table and the MV, and apm, a stateless ingestion layer, has no read table.
CLOUD_READ_TABLE_ROLES = [*LOCAL_WRITE_PATH_ROLES, NodeRole.LOGS, NodeRole.BATCH_EXPORTS]
CLOUD_WRITE_PATH_ROLES = [*CLOUD_READ_TABLE_ROLES, NodeRole.APM]


def write_path_roles() -> list[NodeRole]:
    return CLOUD_WRITE_PATH_ROLES if run_mode().is_deployed_cloud else LOCAL_WRITE_PATH_ROLES


def read_table_roles() -> list[NodeRole]:
    return CLOUD_READ_TABLE_ROLES if run_mode().is_deployed_cloud else [NodeRole.ALL]


def ADD_COLUMN_SQL(table: str) -> str:
    return f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS lc_is_scout_experiment SimpleAggregateFunction(max, Bool) AFTER lc_estimated_bytes"


def ALTER(sql: str, node_roles: list[NodeRole], is_alter_on_replicated_table: bool = False):
    return run_sql_with_exceptions(
        sql,
        node_roles=node_roles,
        sharded=False,
        is_alter_on_replicated_table=is_alter_on_replicated_table,
    )


# Storage first, then the write path, then the MV, so no MV writes a column its target lacks.
operations = [
    ALTER(ADD_COLUMN_SQL(SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE), [NodeRole.OPS], is_alter_on_replicated_table=True),
    ALTER(ADD_COLUMN_SQL(QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE), [NodeRole.OPS]),
    ALTER(ADD_COLUMN_SQL(WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE), write_path_roles()),
    ALTER(f"ALTER TABLE {QUERY_LOG_ARCHIVE_V3_MV} MODIFY QUERY {MV_SELECT_SQL_V3}", write_path_roles()),
    ALTER(ADD_COLUMN_SQL(QUERY_LOG_ARCHIVE_DATA_TABLE), read_table_roles()),
]
