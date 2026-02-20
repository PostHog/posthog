from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import (
    DROP_KAFKA_PERSONS_TABLE_SQL,
    DROP_PERSONS_TABLE_MV_SQL,
    KAFKA_PERSONS_TABLE_SQL,
    PERSONS_TABLE,
    PERSONS_TABLE_MV_SQL,
    PERSONS_WRITABLE_TABLE,
)

operations = [
    # Drop the MV and Kafka table first (these live on ingestion nodes since migration 0152)
    run_sql_with_exceptions(DROP_PERSONS_TABLE_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_KAFKA_PERSONS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    # Add last_seen_at column to the target tables
    # Writable table - Distributed engine (not replicated MergeTree)
    run_sql_with_exceptions(
        f"ALTER TABLE {PERSONS_WRITABLE_TABLE} ADD COLUMN IF NOT EXISTS last_seen_at Nullable(DateTime64)",
        sharded=False,
        is_alter_on_replicated_table=False,
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # Person table - ReplicatedReplacingMergeTree (non-sharded)
    run_sql_with_exceptions(
        f"ALTER TABLE {PERSONS_TABLE} ADD COLUMN IF NOT EXISTS last_seen_at Nullable(DateTime64)",
        sharded=False,
        is_alter_on_replicated_table=True,
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # Recreate the Kafka table and MV (these live on ingestion nodes)
    run_sql_with_exceptions(KAFKA_PERSONS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(PERSONS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
]
