from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DISTRIBUTED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_OPS_MV,
    QUERY_LOG_ARCHIVE_OPS_MV_SQL,
    QUERY_LOG_ARCHIVE_WRITABLE_MV,
    SHARDED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL,
    SHARDED_QUERY_LOG_ARCHIVE_TABLE,
    WRITABLE_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL,
    WRITABLE_QUERY_LOG_ARCHIVE_TABLE,
)

# Rebuild query_log_archive as a single JSON-backed data table living ONLY on the OPS
# cluster, with a Distributed read table (query_log_archive) on every cluster and a
# Distributed write table (writable_query_log_archive) that ships each cluster's logs
# into OPS. See docs/plans/2026-06-09-query-log-archive-rebuild.md.
#
# PRE-FLIGHT AUDIT (coordinate with the ClickHouse team before applying in prod):
# run `SHOW CREATE TABLE query_log_archive` / `sharded_query_log_archive` on each cluster
# to confirm the current object. The operations below are written defensively
# (CREATE IF NOT EXISTS, DROP IF EXISTS, RENAME ... IF EXISTS) so they are safe whether
# the old query_log_archive is a populated data table (satellites) or a no-data
# Distributed (main). Populated tables are renamed aside, never dropped here — the
# ClickHouse team drops the *_legacy tables later and a follow-up migration adds the
# matching DROP for schema parity.

# Clusters that produce their own system.query_log and ship it into OPS.
PRODUCING_ROLES = [
    NodeRole.DATA,
    NodeRole.ENDPOINTS,
    NodeRole.AUX,
    NodeRole.AI_EVENTS,
    NodeRole.SESSIONS,
]
# Every cluster gets the Distributed read table (OPS reads its own data too).
READ_ROLES = [*PRODUCING_ROLES, NodeRole.OPS]

# Legacy MV names from the previous generations, retired below.
OLD_OPS_MV = "query_log_archive_mv"  # satellites/OPS local MV (schema.py bootstrap)
OLD_SHARDED_MV = "sharded_query_log_archive_mv"  # main cluster local MV (0196)
OLD_DIST_MV = "dist_query_log_archive_mv"  # endpoints MV (0196)

operations = [
    # ---------- 1. New JSON-backed data table on OPS only ----------
    run_sql_with_exceptions(
        SHARDED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(),
        node_roles=[NodeRole.OPS],
    ),
    # ---------- 2. OPS archives its own system.query_log locally ----------
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_OPS_MV_SQL(view_name=QUERY_LOG_ARCHIVE_OPS_MV, dest_table=SHARDED_QUERY_LOG_ARCHIVE_TABLE),
        node_roles=[NodeRole.OPS],
    ),
    # ---------- 3. Writable Distributed (physical columns only) on producing clusters ----------
    *[
        run_sql_with_exceptions(
            WRITABLE_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(),
            node_roles=[role],
        )
        for role in PRODUCING_ROLES
    ],
    # ---------- 4. New MVs ship each producing cluster's logs into OPS ----------
    *[
        run_sql_with_exceptions(
            QUERY_LOG_ARCHIVE_OPS_MV_SQL(
                view_name=QUERY_LOG_ARCHIVE_WRITABLE_MV, dest_table=WRITABLE_QUERY_LOG_ARCHIVE_TABLE
            ),
            node_roles=[role],
        )
        for role in PRODUCING_ROLES
    ],
    # ---------- 5. Retire the old MVs (stops writes into the previous generation) ----------
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {OLD_SHARDED_MV}", node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {OLD_DIST_MV}", node_roles=[NodeRole.ENDPOINTS]),
    *[
        run_sql_with_exceptions(f"DROP TABLE IF EXISTS {OLD_OPS_MV}", node_roles=[role])
        for role in [NodeRole.OPS, NodeRole.AUX, NodeRole.AI_EVENTS, NodeRole.SESSIONS]
    ],
    # ---------- 6. Swap the read table: query_log_archive -> Distributed over OPS, everywhere ----------
    # The old query_log_archive is a no-data Distributed on the main cluster but a populated
    # plain table on satellites; rename aside in both cases (no data loss), then recreate.
    *[
        run_sql_with_exceptions(
            f"RENAME TABLE IF EXISTS {QUERY_LOG_ARCHIVE_DATA_TABLE} TO query_log_archive_legacy",
            node_roles=[role],
        )
        for role in READ_ROLES
    ],
    *[
        run_sql_with_exceptions(
            DISTRIBUTED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(),
            node_roles=[role],
        )
        for role in READ_ROLES
    ],
    # ---------- 7. Rename the old populated main-cluster data table aside for CH-team cleanup ----------
    run_sql_with_exceptions(
        f"RENAME TABLE IF EXISTS {SHARDED_QUERY_LOG_ARCHIVE_TABLE} TO sharded_query_log_archive_legacy",
        node_roles=[NodeRole.DATA],
    ),
]
