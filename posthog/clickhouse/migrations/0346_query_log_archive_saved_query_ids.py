"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_ADD_SAVED_QUERY_IDS_ALIAS_SQL,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    SHARDED_QUERY_LOG_ARCHIVE_TABLE,
)

# NOTE: query_log_archive also lives on non-targetable node(s): batch_exports (dump-baselined; no NodeRole member) — this migration cannot create it there

operations = [
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_SAVED_QUERY_IDS_ALIAS_SQL(SHARDED_QUERY_LOG_ARCHIVE_TABLE),
        node_roles=[NodeRole.OPS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_SAVED_QUERY_IDS_ALIAS_SQL(QUERY_LOG_ARCHIVE_DATA_TABLE),
        node_roles=[
            NodeRole.DATA,
            NodeRole.ENDPOINTS,
            NodeRole.AUX,
            NodeRole.BATCH_EXPORTS,
            NodeRole.AI_EVENTS,
            NodeRole.SESSIONS,
            NodeRole.LOGS,
            NodeRole.OPS,
            NodeRole.INGESTION_EVENTS,
            NodeRole.INGESTION_SMALL,
            NodeRole.INGESTION_MEDIUM,
        ],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
