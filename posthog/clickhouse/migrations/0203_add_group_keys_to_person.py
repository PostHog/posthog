"""
Add group_0_key through group_4_key columns to the person table.

This enables joining persons to groups for feature flag mixed targeting
(targeting users by both person properties AND group properties).

The migration:
1. Adds new columns to the main person table
2. Recreates the Kafka table, writable table, and materialized view with new columns
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
    PERSONS_WRITABLE_TABLE_SQL,
)

ADD_GROUP_KEY_COLUMNS_SQL = f"""
ALTER TABLE IF EXISTS {PERSONS_TABLE}
ADD COLUMN IF NOT EXISTS group_0_key VARCHAR DEFAULT '',
ADD COLUMN IF NOT EXISTS group_1_key VARCHAR DEFAULT '',
ADD COLUMN IF NOT EXISTS group_2_key VARCHAR DEFAULT '',
ADD COLUMN IF NOT EXISTS group_3_key VARCHAR DEFAULT '',
ADD COLUMN IF NOT EXISTS group_4_key VARCHAR DEFAULT ''
"""

DROP_WRITABLE_PERSONS_TABLE_SQL = f"DROP TABLE IF EXISTS {PERSONS_WRITABLE_TABLE}"

operations = [
    # 1. Add columns to the main person table (replicated, non-sharded)
    run_sql_with_exceptions(
        ADD_GROUP_KEY_COLUMNS_SQL,
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
    ),
    # 2. Drop the materialized view (on ingestion layer)
    run_sql_with_exceptions(DROP_PERSONS_TABLE_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    # 3. Drop the Kafka table (on ingestion layer)
    run_sql_with_exceptions(DROP_KAFKA_PERSONS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    # 4. Drop the writable distributed table (on ingestion layer)
    run_sql_with_exceptions(DROP_WRITABLE_PERSONS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    # 5. Recreate the writable distributed table with new columns
    run_sql_with_exceptions(PERSONS_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    # 6. Recreate the Kafka table with new columns
    run_sql_with_exceptions(KAFKA_PERSONS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    # 7. Recreate the materialized view with new columns
    run_sql_with_exceptions(PERSONS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
]
