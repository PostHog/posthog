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

# Archives the warehouse table ids that HogQL writes into log_comment as warehouse_table_ids.
# Rows archived before this migration keep an empty array: there is no backfill.
#
# Every table on the write path gets the column first, then the MV starts to fill it. MODIFY QUERY
# swaps the MV select in one step, so no row of system.query_log is missed in between. ADD COLUMN IF NOT
# EXISTS lets a stack that already built the column from 0273 run it again.

COLUMN = "lc_warehouse_table_ids SimpleAggregateFunction(max, Array(String))"
AFTER = "AFTER lc_estimated_bytes"

READ_ROLES = [
    NodeRole.DATA,
    NodeRole.AUX,
    NodeRole.AI_EVENTS,
    NodeRole.SESSIONS,
    NodeRole.LOGS,
    NodeRole.OPS,
    NodeRole.INGESTION_EVENTS,
    NodeRole.INGESTION_SMALL,
    NodeRole.INGESTION_MEDIUM,
]
WRITE_ROLES = [
    NodeRole.DATA,
    NodeRole.AUX,
    NodeRole.AI_EVENTS,
    NodeRole.SESSIONS,
    NodeRole.LOGS,
    NodeRole.METRICS,
    NodeRole.OPS,
    NodeRole.INGESTION_METRICS,
]


def add_column(table: str) -> str:
    return f"ALTER TABLE posthog.{table} ADD COLUMN IF NOT EXISTS {COLUMN} {AFTER}"


operations = [
    run_sql_with_exceptions(
        add_column(SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE),
        node_roles=[NodeRole.OPS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    *(
        run_sql_with_exceptions(add_column(table), node_roles=roles, sharded=False, is_alter_on_replicated_table=False)
        for table, roles in (
            (QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE, [NodeRole.OPS]),
            (WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE, WRITE_ROLES),
            (QUERY_LOG_ARCHIVE_DATA_TABLE, READ_ROLES),
        )
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE posthog.{QUERY_LOG_ARCHIVE_V3_MV} MODIFY QUERY {MV_SELECT_SQL_V3}",
        node_roles=WRITE_ROLES,
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
