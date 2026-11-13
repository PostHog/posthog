from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Nothing writes or reads session_replay_features any more, so every object of the family goes.
# The views and Kafka tables go first so that no consumer writes into a table that is being dropped.
# prod-eu still runs the MSK Kafka table and its view on the data nodes, so those drops also target DATA.

operations = [
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS session_replay_features_ws_mv",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS session_replay_features_mv",
        node_roles=[NodeRole.INGESTION_MEDIUM, NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS kafka_session_replay_features_ws",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS kafka_session_replay_features",
        node_roles=[NodeRole.INGESTION_MEDIUM, NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS writable_session_replay_features",
        node_roles=[NodeRole.INGESTION_MEDIUM, NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS session_replay_features",
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS sharded_session_replay_features SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.AUX],
    ),
]
