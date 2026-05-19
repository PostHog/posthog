from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_feature_sql import (
    DISTRIBUTED_SESSION_REPLAY_FEATURES_TABLE_SQL,
    KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL,
    SESSION_REPLAY_FEATURES_TABLE_MV_SQL,
    SESSION_REPLAY_FEATURES_TABLE_SQL,
    WRITABLE_SESSION_REPLAY_FEATURES_TABLE_SQL,
)

operations = [
    # Sharded data table on AUX nodes (single-shard satellite cluster)
    run_sql_with_exceptions(SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.AUX]),
    # Distributed read table on AUX nodes (co-located with the source-of-truth table)
    run_sql_with_exceptions(DISTRIBUTED_SESSION_REPLAY_FEATURES_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    # Writable distributed table on INGESTION_MEDIUM nodes
    run_sql_with_exceptions(WRITABLE_SESSION_REPLAY_FEATURES_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    # Kafka table on INGESTION_MEDIUM nodes (requires msk_cluster named collection)
    run_sql_with_exceptions(
        KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    # Materialized view on INGESTION_MEDIUM nodes
    run_sql_with_exceptions(
        SESSION_REPLAY_FEATURES_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
]
