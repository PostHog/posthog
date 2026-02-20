from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    ADD_IS_DELETED_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_IS_DELETED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_IS_DELETED_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
)

operations = [
    # Drop the MV and Kafka table first (these live on ingestion nodes)
    run_sql_with_exceptions(
        DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    # Add is_deleted column to the target tables
    # Writable table - Distributed engine (not replicated MergeTree)
    run_sql_with_exceptions(
        ADD_IS_DELETED_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        sharded=False,
        is_alter_on_replicated_table=False,
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # Distributed table for reads - Distributed engine
    run_sql_with_exceptions(
        ADD_IS_DELETED_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # Sharded table - ReplicatedAggregatingMergeTree
    run_sql_with_exceptions(
        ADD_IS_DELETED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # Recreate the Kafka table and MV (these live on ingestion nodes)
    run_sql_with_exceptions(
        KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
]
