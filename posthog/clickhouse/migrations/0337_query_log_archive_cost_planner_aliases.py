"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_ADD_COST_PLANNER_ALIASES_SQL,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    SHARDED_QUERY_LOG_ARCHIVE_TABLE,
)

# Roles that carry the Distributed read table: the 0273 roles plus the roles the HCL composes it on.
READ_TABLE_ROLES = [
    NodeRole.DATA,
    NodeRole.ENDPOINTS,
    NodeRole.AUX,
    NodeRole.AI_EVENTS,
    NodeRole.SESSIONS,
    NodeRole.LOGS,
    NodeRole.OPS,
    NodeRole.BATCH_EXPORTS,
    NodeRole.INGESTION_EVENTS,
    NodeRole.INGESTION_SMALL,
    NodeRole.INGESTION_MEDIUM,
]

# Read-time ALIAS columns over log_comment paths the HogQL cost planner emits as query tags. The JSON
# column already stores those paths, so this is metadata only: no data is rewritten and the writable,
# buffer and MV are untouched because they carry physical columns only.
operations = [
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_COST_PLANNER_ALIASES_SQL(SHARDED_QUERY_LOG_ARCHIVE_TABLE),
        node_roles=[NodeRole.OPS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    # 0273 created the Distributed read table on every node of that time. Nodes added later
    # can lack it, so skip them instead of aborting the run.
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_COST_PLANNER_ALIASES_SQL(QUERY_LOG_ARCHIVE_DATA_TABLE),
        node_roles=READ_TABLE_ROLES,
        sharded=False,
        is_alter_on_replicated_table=False,
        skip_if_table_missing=QUERY_LOG_ARCHIVE_DATA_TABLE,
    ),
]
