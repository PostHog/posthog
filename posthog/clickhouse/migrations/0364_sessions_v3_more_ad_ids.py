from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sessions_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3,
    DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL_V3,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_RECORDINGS_SQL_V3,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL_V3,
    DROP_RAW_SESSION_SHARDED_TABLE_SQL_V3,
    DROP_RAW_SESSION_VIEW_SQL_V3,
    DROP_RAW_SESSION_WRITABLE_TABLE_SQL_V3,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3,
    RAW_SESSIONS_TABLE_MV_RECORDINGS_SQL_V3,
    RAW_SESSIONS_TABLE_MV_SQL_V3,
    SHARDED_RAW_SESSIONS_TABLE_SQL_V3,
    WRITABLE_RAW_SESSIONS_TABLE_SQL_V3,
)
from posthog.run_mode import run_mode

# raw_sessions_v3 has a new shape: no entry_ad_ids_map or flag_keys, the ad-ids set holds
# 'key=value' pairs, and the counts are uniq states instead of uniqExact. A shape change cannot be
# applied with ALTER, so an existing v3 table has to be rebuilt with a backfill.
#
# Cloud is applied by hand by the ClickHouse team, because the rebuild needs a backfill and
# dropping the ingestion MV stops v3 ingestion. As of 2026-10-28, prod-us is done; dev and EU are
# still to do. The declared cloud schema is the HCL in posthog/clickhouse/hcl/.
#
# Everywhere else (fresh installs, CI, the test database, self-hosted upgrades) this migration
# drops the v3 tables and creates them again from the current definitions. 0178 dropped the MVs and
# this is the only migration that creates them again. An MV cannot be created on top of a table
# with the old shape (uniq into uniqExact fails), so an upgraded install must get new tables. Off
# cloud, nothing has written to v3 since 0178 and the default session table is v2, so the dropped
# rows are stale. A rebuild also removes flag_keys and the bloom filter indexes that 0180 and 0325
# put back on top of today's base SQL, so the result matches the declared HCL.
REBUILD_RAW_SESSIONS_V3 = [
    run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_RECORDINGS_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_RAW_SESSION_VIEW_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_RAW_SESSION_WRITABLE_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_RAW_SESSION_SHARDED_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(SHARDED_RAW_SESSIONS_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(WRITABLE_RAW_SESSIONS_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_RECORDINGS_SQL_V3(), node_roles=[NodeRole.DATA]),
]

operations = [] if run_mode().is_deployed_cloud else REBUILD_RAW_SESSIONS_V3
