from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    ADD_SURFACING_SCORE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_SURFACING_SCORE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_SURFACING_SCORE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
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

# Add surfacing_score to session_replay_events. Cloud uses WarpStream and is dropping MSK;
# non-cloud only has MSK.

_IS_CLOUD = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")

operations = [
    # Drop MV + Kafka tables (DROP IF EXISTS, so WS drops no-op in non-cloud).
    run_sql_with_exceptions(
        DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_WS_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    # Add the column: sharded, distributed, writable.
    run_sql_with_exceptions(
        ADD_SURFACING_SCORE_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_SURFACING_SCORE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_SURFACING_SCORE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        sharded=False,
        is_alter_on_replicated_table=False,
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # Recreate Kafka + MV: WarpStream in cloud, MSK elsewhere.
    *(
        [
            run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
            run_sql_with_exceptions(SESSION_REPLAY_EVENTS_WS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
        ]
        if _IS_CLOUD
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
