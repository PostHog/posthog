"""
Add group_0_key through group_4_key columns to the person table.

This enables joining persons to groups for feature flag mixed targeting
(targeting users by both person properties AND group properties).
"""

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

GROUP_KEY_COLUMNS = [f"group_{i}_key" for i in range(5)]

ADD_COLUMN_SQL = "ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} VARCHAR DEFAULT ''"

operations = [
    # 1. Drop the MV and Kafka table first (these live on ingestion nodes since migration 0152)
    run_sql_with_exceptions(DROP_PERSONS_TABLE_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_KAFKA_PERSONS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    # 2. Add columns to the writable table (Distributed engine, not replicated)
    *[
        run_sql_with_exceptions(
            ADD_COLUMN_SQL.format(table=PERSONS_WRITABLE_TABLE, column=col),
            sharded=False,
            is_alter_on_replicated_table=False,
            node_roles=[NodeRole.INGESTION_SMALL],
        )
        for col in GROUP_KEY_COLUMNS
    ],
    # 3. Add columns to the main person table (ReplicatedReplacingMergeTree)
    *[
        run_sql_with_exceptions(
            ADD_COLUMN_SQL.format(table=PERSONS_TABLE, column=col),
            sharded=False,
            is_alter_on_replicated_table=True,
            node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        )
        for col in GROUP_KEY_COLUMNS
    ],
    # 4. Recreate the Kafka table and MV with the new columns
    run_sql_with_exceptions(KAFKA_PERSONS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(PERSONS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
]
