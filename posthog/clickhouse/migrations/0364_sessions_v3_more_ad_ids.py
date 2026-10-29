from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sessions_v3 import (
    RAW_SESSIONS_TABLE_MV_RECORDINGS_SQL_V3,
    RAW_SESSIONS_TABLE_MV_SQL_V3,
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
# Everywhere else (fresh installs, CI, the test database) this migration is required: the earlier
# v3 migrations render the current table and view definitions, but 0178 dropped the MVs, and this
# is the only migration that creates them again. Both statements are CREATE ... IF NOT EXISTS, so
# an existing MV is kept. An install that created v3 before the shape change keeps the old shape.
# To use sessionTableVersion v3 there, drop raw_sessions_v3_mv, raw_sessions_v3_recordings_mv,
# raw_sessions_v3_v, raw_sessions_v3, writable_raw_sessions_v3 and sharded_raw_sessions_v3, then
# create them again from the definitions in posthog/models/raw_sessions/sessions_v3.py.
operations = (
    []
    if run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_RECORDINGS_SQL_V3(), node_roles=[NodeRole.DATA]),
    ]
)
