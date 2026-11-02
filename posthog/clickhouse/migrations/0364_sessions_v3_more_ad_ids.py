from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.migrations_v3 import (
    DROP_FLAG_KEY_VALUES_BLOOM_FILTER,
    DROP_FLAG_KEYS,
    DROP_FLAG_KEYS_BLOOM_FILTER,
)
from posthog.models.raw_sessions.sessions_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_V3,
    RAW_SESSIONS_TABLE_MV_RECORDINGS_SQL_V3,
    RAW_SESSIONS_TABLE_MV_SQL_V3,
    SHARDED_RAW_SESSIONS_TABLE_V3,
    WRITABLE_RAW_SESSIONS_TABLE_V3,
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
#
# The drops come first. 0180 and 0325 replay on a fresh cluster and put flag_keys and the two
# bloom filter indexes back on top of today's base SQL, which no longer declares them, so without
# these statements a fresh install ends up with a table the declared HCL does not describe.
DROP_SUPERSEDED_FLAG_COLUMNS = [
    run_sql_with_exceptions(
        DROP_FLAG_KEYS_BLOOM_FILTER.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        DROP_FLAG_KEY_VALUES_BLOOM_FILTER.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        DROP_FLAG_KEYS.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        DROP_FLAG_KEYS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        DROP_FLAG_KEYS.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]

operations = (
    []
    if run_mode().is_deployed_cloud
    else [
        *DROP_SUPERSEDED_FLAG_COLUMNS,
        run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_RECORDINGS_SQL_V3(), node_roles=[NodeRole.DATA]),
    ]
)
