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

operations = [
    run_sql_with_exceptions(
        DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_WS_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    *(
        [
            run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
            run_sql_with_exceptions(
                SESSION_REPLAY_EVENTS_WS_MV_SQL(exclude_columns=["snapshot_mode_v2"]),
                node_roles=[NodeRole.INGESTION_SMALL],
            ),
        ]
        if run_mode().is_deployed_cloud
        else [
            run_sql_with_exceptions(
                KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
            ),
            run_sql_with_exceptions(
                SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False, exclude_columns=["snapshot_mode_v2"]),
                node_roles=[NodeRole.INGESTION_SMALL],
            ),
        ]
    ),
]
