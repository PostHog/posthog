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

# Add surfacing_score to session_replay_events. Mirrors 0231_add_ai_columns_to_session_replay_events.py
# but also drops/recreates the WarpStream Kafka table + MV introduced in 0246, since they share the
# same base schema. The surfacing scoring sweep writes partial-row Kafka messages that flow
# through these MVs.

_IS_CLOUD = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")

operations = [
    # 1. Drop the MSK MV + Kafka table so they stop consuming from the topic while we alter.
    run_sql_with_exceptions(
        DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    # 2. Drop the WarpStream MV + Kafka table too (cloud-only, created in 0246).
    *(
        [
            run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_WS_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
            run_sql_with_exceptions(
                DROP_KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]
            ),
        ]
        if _IS_CLOUD
        else []
    ),
    # 3. Add the column to the target tables — sharded first, then distributed, then writable.
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
    # 4. Recreate the MSK Kafka table + MV with the new column wired through.
    run_sql_with_exceptions(
        KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    # 5. Recreate the WarpStream Kafka table + MV (cloud-only).
    *(
        [
            run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
            run_sql_with_exceptions(SESSION_REPLAY_EVENTS_WS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
        ]
        if _IS_CLOUD
        else []
    ),
]
