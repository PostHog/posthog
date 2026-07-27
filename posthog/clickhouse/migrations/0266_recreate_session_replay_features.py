from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_feature_sql import (
    DISTRIBUTED_SESSION_REPLAY_FEATURES_TABLE_SQL,
    KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL,
    KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL,
    SESSION_REPLAY_FEATURES_TABLE_MV_SQL,
    SESSION_REPLAY_FEATURES_TABLE_SQL,
    SESSION_REPLAY_FEATURES_WS_MV_SQL,
    WRITABLE_SESSION_REPLAY_FEATURES_TABLE_SQL,
)

# Recreate session_replay_features from scratch.

_is_cloud = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")

operations = [
    # 1. Sharded storage on AUX.
    run_sql_with_exceptions(
        SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=False),
        node_roles=[NodeRole.AUX],
    ),
    # 2. Read-side Distributed on AUX.
    run_sql_with_exceptions(
        DISTRIBUTED_SESSION_REPLAY_FEATURES_TABLE_SQL(
            on_cluster=False,
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
    # 3. Writable Distributed on INGESTION_MEDIUM.
    run_sql_with_exceptions(
        WRITABLE_SESSION_REPLAY_FEATURES_TABLE_SQL(
            on_cluster=False,
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 4. Kafka consumer + MV.
    *(
        [
            run_sql_with_exceptions(
                KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL(),
                node_roles=[NodeRole.INGESTION_MEDIUM],
            ),
            run_sql_with_exceptions(
                SESSION_REPLAY_FEATURES_WS_MV_SQL(),
                node_roles=[NodeRole.INGESTION_MEDIUM],
            ),
        ]
        if _is_cloud
        else [
            run_sql_with_exceptions(
                KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=False),
                node_roles=[NodeRole.INGESTION_MEDIUM],
            ),
            run_sql_with_exceptions(
                SESSION_REPLAY_FEATURES_TABLE_MV_SQL(on_cluster=False),
                node_roles=[NodeRole.INGESTION_MEDIUM],
            ),
        ]
    ),
]
