from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DISTRIBUTED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_OPS_MV,
    QUERY_LOG_ARCHIVE_OPS_MV_SQL,
    SHARDED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL,
    SHARDED_QUERY_LOG_ARCHIVE_TABLE,
    WRITABLE_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL,
    WRITABLE_QUERY_LOG_ARCHIVE_TABLE,
)

# Rebuild query_log_archive as a JSON-backed data table living on the OPS cluster:
#   - sharded_query_log_archive : OPS data table, stores log_comment as a curated JSON column and
#     ProfileEvents as the raw Map; every lc_* / ProfileEvents_* column is a read-time ALIAS.
#   - query_log_archive         : Distributed read table over ops.sharded_query_log_archive, everywhere.
#   - writable_query_log_archive: Distributed write table (physical columns only), everywhere.
#   - ops_query_log_archive_mv  : slim MV (system.query_log -> writable), on every cluster.
#
# This migration is idempotent and converges TWO divergent starting states:
#   (A) Production, set up by hand: query_log_archive is the *data table* on OPS, writable_query_log_archive
#       and ops_query_log_archive_mv already exist (old schema, all lc_*/ProfileEvents_* physical).
#   (B) Repo migration history (0196+): sharded_query_log_archive is the data table, with
#       sharded_query_log_archive_mv / dist_query_log_archive_mv MVs.
# The old OPS data table is renamed to query_log_archive_old (NOT dropped) so it can be backfilled into
# the new table manually; the ClickHouse team drops it afterwards.

# Every cluster produces its own system.query_log, archives it into OPS via the writable table, and can
# read it back through the Distributed query_log_archive.
ALL_ROLES = [
    NodeRole.DATA,
    NodeRole.ENDPOINTS,
    NodeRole.AUX,
    NodeRole.AI_EVENTS,
    NodeRole.SESSIONS,
    NodeRole.OPS,
]
QUERY_LOG_ARCHIVE_OLD_TABLE = "query_log_archive_old"  # renamed OPS data table, kept for manual backfill
SHARDED_OLD_TABLE = "sharded_query_log_archive_old"  # renamed repo-history data table (state B)

# Previous-generation MV names retired here (prod uses ops_query_log_archive_mv; history uses the others).
OLD_SHARDED_MV = "sharded_query_log_archive_mv"
OLD_DIST_MV = "dist_query_log_archive_mv"

operations = [
    # ---------- A. Stop the old write path (MVs hold no data) ----------
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {QUERY_LOG_ARCHIVE_OPS_MV}", node_roles=ALL_ROLES),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {OLD_SHARDED_MV}", node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {OLD_DIST_MV}", node_roles=[NodeRole.ENDPOINTS]),
    # ---------- B. Move the old populated data tables aside (no data dropped) ----------
    # State B: the repo-history sharded data table collides with the new JSON table name.
    run_sql_with_exceptions(
        f"RENAME TABLE IF EXISTS {SHARDED_QUERY_LOG_ARCHIVE_TABLE} TO {SHARDED_OLD_TABLE}",
        node_roles=[NodeRole.DATA],
    ),
    # State A: the production OPS data table. Kept as query_log_archive_old for the manual backfill.
    run_sql_with_exceptions(
        f"RENAME TABLE IF EXISTS {QUERY_LOG_ARCHIVE_DATA_TABLE} TO {QUERY_LOG_ARCHIVE_OLD_TABLE}",
        node_roles=[NodeRole.OPS],
    ),
    # ---------- C. New JSON-backed data table on OPS ----------
    run_sql_with_exceptions(SHARDED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(), node_roles=[NodeRole.OPS]),
    # ---------- D. Writable Distributed (physical columns only) -> ops.sharded, on every cluster ----------
    # Drop first to replace prod's existing old-schema writable (a no-data Distributed).
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {WRITABLE_QUERY_LOG_ARCHIVE_TABLE}", node_roles=ALL_ROLES),
    run_sql_with_exceptions(WRITABLE_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(), node_roles=ALL_ROLES),
    # ---------- E. Slim MV (system.query_log -> writable), on every cluster ----------
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_OPS_MV_SQL(view_name=QUERY_LOG_ARCHIVE_OPS_MV, dest_table=WRITABLE_QUERY_LOG_ARCHIVE_TABLE),
        node_roles=ALL_ROLES,
    ),
    # ---------- F. Read Distributed query_log_archive -> ops.sharded, on EVERY node ----------
    # Created everywhere so query_log_archive is queryable from any node. Safe to drop on every node:
    # the only place it is a populated data table is OPS, already renamed aside in B.
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {QUERY_LOG_ARCHIVE_DATA_TABLE}", node_roles=[NodeRole.ALL]),
    run_sql_with_exceptions(DISTRIBUTED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(), node_roles=[NodeRole.ALL]),
]
