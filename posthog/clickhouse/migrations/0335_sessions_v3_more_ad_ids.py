from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sessions_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3,
    DROP_KAFKA_RAW_SESSIONS_V3_TABLE_SQL,
    DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL_V3,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_RECORDINGS_SQL_V3,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL_V3,
    DROP_RAW_SESSION_SHARDED_TABLE_SQL_V3,
    DROP_RAW_SESSION_VIEW_SQL_V3,
    DROP_RAW_SESSION_WRITABLE_TABLE_SQL_V3,
    DROP_RAW_SESSIONS_V3_EVENTS_WS_MV_SQL,
    KAFKA_RAW_SESSIONS_V3_TABLE_SQL,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3,
    RAW_SESSIONS_TABLE_MV_RECORDINGS_SQL_V3,
    RAW_SESSIONS_TABLE_MV_SQL_V3,
    RAW_SESSIONS_V3_EVENTS_WS_MV_SQL,
    SHARDED_RAW_SESSIONS_TABLE_SQL_V3,
    WRITABLE_RAW_SESSIONS_INGESTION_TABLE_SQL_V3,
    WRITABLE_RAW_SESSIONS_TABLE_SQL_V3,
)
from posthog.run_mode import run_mode

# raw_sessions_v3 changes shape here (entry_ad_ids_map and flag_keys dropped, the ad-ids set
# becomes 'key=value' pairs, uniqExact states become uniq), which cannot be ALTERed, so the
# pipeline objects are recreated.
#
# In cloud only the ingestion-events layer is repo-managed: the sessions-cluster MergeTree is
# recreated and backfilled by the ClickHouse team out of band, and the legacy main-cluster
# copies are left untouched for them to retire. The Kafka table keeps its consumer group, so
# consumption resumes from committed offsets (lag, not loss).
#
# Outside cloud this recreates the whole local pipeline, dropping any locally accumulated v3
# rows. This also re-enables v3 event ingestion on installs that migrated through 0178, which
# dropped the MV; that is intentional, v3 is the go-forward sessions table.
operations = (
    [
        run_sql_with_exceptions(DROP_RAW_SESSIONS_V3_EVENTS_WS_MV_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
        run_sql_with_exceptions(DROP_KAFKA_RAW_SESSIONS_V3_TABLE_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
        run_sql_with_exceptions(DROP_RAW_SESSION_WRITABLE_TABLE_SQL_V3(), node_roles=[NodeRole.INGESTION_EVENTS]),
        run_sql_with_exceptions(WRITABLE_RAW_SESSIONS_INGESTION_TABLE_SQL_V3(), node_roles=[NodeRole.INGESTION_EVENTS]),
        run_sql_with_exceptions(KAFKA_RAW_SESSIONS_V3_TABLE_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
        run_sql_with_exceptions(RAW_SESSIONS_V3_EVENTS_WS_MV_SQL(), node_roles=[NodeRole.INGESTION_EVENTS]),
    ]
    if run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_RECORDINGS_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(DROP_RAW_SESSION_VIEW_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(DROP_RAW_SESSION_WRITABLE_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(DROP_RAW_SESSION_SHARDED_TABLE_SQL_V3(), node_roles=[NodeRole.DATA], sharded=True),
        run_sql_with_exceptions(SHARDED_RAW_SESSIONS_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(WRITABLE_RAW_SESSIONS_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_RECORDINGS_SQL_V3(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3(), node_roles=[NodeRole.DATA]),
    ]
)
