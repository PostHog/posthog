from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Tear down session_replay_features end-to-end.

operations = [
    # 1. Materialized views.
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS session_replay_features_mv",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS session_replay_features_ws_mv",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 2. Kafka consumer tables (MSK + WarpStream).
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS kafka_session_replay_features",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS kafka_session_replay_features_ws",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 3. writable_session_replay_features Distributed.
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS writable_session_replay_features",
        node_roles=[NodeRole.INGESTION_MEDIUM, NodeRole.DATA],
    ),
    # 4. Read-side Distributed table.
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS session_replay_features",
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
    # 5. Sharded.
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS sharded_session_replay_features SYNC",
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
