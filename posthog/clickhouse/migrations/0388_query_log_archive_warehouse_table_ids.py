from django.conf import settings

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

# Archives the warehouse table ids that HogQL writes into log_comment as warehouse_table_ids.
# Rows archived before this migration keep an empty array: there is no backfill.
#
# Every table on the write path gets the column first, then the MV starts to fill it. MODIFY QUERY
# swaps the MV select in one step, so no row of system.query_log is missed in between. ADD COLUMN IF NOT
# EXISTS lets a stack that already built the column from 0273 run it again.

COLUMN = "lc_warehouse_table_ids SimpleAggregateFunction(max, Array(String))"
AFTER = "AFTER lc_estimated_bytes"

# The roles that hold each object differ between the cloud clusters and the local multinode stack,
# so each deployment lists the roles its HCL goldens declare: dev, prod-us and prod-eu for cloud,
# local-multi for the rest. A role without the table fails the ALTER, so do not add a role the
# golden lacks. The multinode migration smoke checks the local list.
if run_mode().is_deployed_cloud:
    READ_ROLES = [
        NodeRole.DATA,
        NodeRole.AUX,
        NodeRole.AI_EVENTS,
        NodeRole.SESSIONS,
        NodeRole.LOGS,
        NodeRole.OPS,
        NodeRole.BATCH_EXPORTS,
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
        NodeRole.APM,
        NodeRole.BATCH_EXPORTS,
    ]
else:
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
        NodeRole.OPS,
    ]


def add_column(table: str) -> str:
    return f"ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{table} ADD COLUMN IF NOT EXISTS {COLUMN} {AFTER}"


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
        f"ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{QUERY_LOG_ARCHIVE_V3_MV} MODIFY QUERY {MV_SELECT_SQL_V3}",
        node_roles=WRITE_ROLES,
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
