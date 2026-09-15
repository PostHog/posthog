from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    DROP_KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_WS_MV_SQL,
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL,
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    SESSION_REPLAY_EVENTS_WS_MV_SQL,
)

ADD_SNAPSHOT_MODE = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS snapshot_mode AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC'))
"""

operations = [
    run_sql_with_exceptions(
        DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_WS_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(
        ADD_SNAPSHOT_MODE.format(table_name="sharded_session_replay_events"),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_SNAPSHOT_MODE.format(table_name="session_replay_events"),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_SNAPSHOT_MODE.format(table_name="writable_session_replay_events"),
        node_roles=[NodeRole.INGESTION_SMALL],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    *(
        [
            run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
            run_sql_with_exceptions(SESSION_REPLAY_EVENTS_WS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
        ]
        if run_mode().is_deployed_cloud
        else [
            run_sql_with_exceptions(
                KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
            ),
            run_sql_with_exceptions(
                SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
            ),
        ]
    ),
]
