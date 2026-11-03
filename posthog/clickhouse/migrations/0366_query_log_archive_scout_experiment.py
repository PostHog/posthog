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

WRITE_PATH_ROLES = [NodeRole.DATA, NodeRole.AUX, NodeRole.AI_EVENTS, NodeRole.SESSIONS, NodeRole.LOGS, NodeRole.OPS]
INGESTION_ROLES = [NodeRole.INGESTION_EVENTS, NodeRole.INGESTION_SMALL, NodeRole.INGESTION_MEDIUM]
# The cloud clusters run the writable table, the MV and the read table on every node, ingestion and APM included.
CLOUD_ROLES = [*WRITE_PATH_ROLES, *INGESTION_ROLES, NodeRole.APM, NodeRole.BATCH_EXPORTS]


def write_path_roles() -> list[NodeRole]:
    return CLOUD_ROLES if run_mode().is_deployed_cloud else WRITE_PATH_ROLES


def read_table_roles() -> list[NodeRole]:
    return CLOUD_ROLES if run_mode().is_deployed_cloud else [*WRITE_PATH_ROLES, *INGESTION_ROLES]


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
