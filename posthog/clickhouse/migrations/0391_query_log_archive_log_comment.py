from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE,
    QUERY_LOG_ARCHIVE_V3_MV,
    QUERY_LOG_ARCHIVE_V3_MV_SQL,
    SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE,
    WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE,
)
from posthog.run_mode import run_mode

# Adds log_comment to the query_log archive. posthog-cloud-infra manages the archive objects on the cloud
# clusters and adds the column there, so this migration does nothing in cloud.
#
# Every table on the write path gets the column before the MV writes it. The MV is dropped and created
# again, because ALTER TABLE ... MODIFY QUERY replaces the aggregate column types that the MV declares with
# the plain types of its SELECT. ADD COLUMN IF NOT EXISTS and CREATE ... IF NOT EXISTS let a stack whose
# 0273 or 0378 already built the column run this migration too.

STORED_COLUMN = (
    "log_comment SimpleAggregateFunction(max, String) "
    "TTL toDateTime(initial_query_start_time) + toIntervalMonth(1) "
    "AFTER lc_estimated_bytes"
)
COLUMN = "log_comment SimpleAggregateFunction(max, String) AFTER lc_estimated_bytes"

# The roles that hold each object in the local multinode stack, as its HCL goldens declare them. A
# single-node stack runs every statement on its one node. A role without the table fails the ALTER.
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


def add_column(table: str, column: str) -> str:
    return f"ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{table} ADD COLUMN IF NOT EXISTS {column}"


operations = (
    []
    if run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(
            add_column(SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE, STORED_COLUMN),
            node_roles=[NodeRole.OPS],
            sharded=False,
            is_alter_on_replicated_table=True,
        ),
        *(
            run_sql_with_exceptions(
                add_column(table, COLUMN), node_roles=roles, sharded=False, is_alter_on_replicated_table=False
            )
            for table, roles in (
                (QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE, [NodeRole.OPS]),
                (WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE, WRITE_ROLES),
                (QUERY_LOG_ARCHIVE_DATA_TABLE, READ_ROLES),
            )
        ),
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{QUERY_LOG_ARCHIVE_V3_MV}",
            node_roles=WRITE_ROLES,
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
        run_sql_with_exceptions(
            QUERY_LOG_ARCHIVE_V3_MV_SQL(), node_roles=WRITE_ROLES, sharded=False, is_alter_on_replicated_table=False
        ),
    ]
)
