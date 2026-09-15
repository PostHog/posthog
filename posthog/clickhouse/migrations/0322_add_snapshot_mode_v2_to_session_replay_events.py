from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode
from posthog.session_recordings.sql.session_replay_event_migrations_sql import DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL
from posthog.session_recordings.sql.session_replay_event_sql import (
    DROP_SESSION_REPLAY_EVENTS_WS_MV_SQL,
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    SESSION_REPLAY_EVENTS_WS_MV_SQL,
)

CHECK_REPLAY_SCHEMA = """
SELECT throwIf(
    countIf(name = 'snapshot_mode') > 0
    OR countIf(
        name = 'snapshot_source'
        AND type = 'AggregateFunction(argMin, Nullable(String), DateTime64(6, ''UTC''))'
    ) != 1,
    'Replay metadata schema is not ready on {table_name}. Complete the ClickHouse cleanup in docs/internal/mobile-replay-capture-mode.md before retrying migration 0322.'
)
FROM system.columns
WHERE database = currentDatabase() AND table = '{table_name}'
"""

ADD_SNAPSHOT_MODE_V2 = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS snapshot_mode_v2 AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))
"""

operations = [
    # Validate every replica before DDL; replicated ALTERs only run on one host per shard.
    run_sql_with_exceptions(
        CHECK_REPLAY_SCHEMA.format(table_name="sharded_session_replay_events"),
        node_roles=[NodeRole.DATA],
        require_hosts=True,
    ),
    run_sql_with_exceptions(
        CHECK_REPLAY_SCHEMA.format(table_name="writable_session_replay_events"),
        node_roles=[NodeRole.DATA, NodeRole.INGESTION_SMALL],
        require_hosts=True,
    ),
    run_sql_with_exceptions(
        CHECK_REPLAY_SCHEMA.format(table_name="session_replay_events"),
        node_roles=[NodeRole.DATA],
        require_hosts=True,
    ),
    run_sql_with_exceptions(
        ADD_SNAPSHOT_MODE_V2.format(table_name="sharded_session_replay_events"),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_SNAPSHOT_MODE_V2.format(table_name="writable_session_replay_events"),
        node_roles=[NodeRole.DATA, NodeRole.INGESTION_SMALL],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_SNAPSHOT_MODE_V2.format(table_name="session_replay_events"),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_WS_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    *(
        [run_sql_with_exceptions(SESSION_REPLAY_EVENTS_WS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL])]
        if run_mode().is_deployed_cloud
        else [
            run_sql_with_exceptions(
                SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
            )
        ]
    ),
]
