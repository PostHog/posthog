"""
Drop group_0_key through group_4_key columns from the person table.

These columns were added in migration 0218 for mixed user+group targeting,
but the design was revised to use event-time group context instead of
persisting group membership on persons. The columns were never populated.

See: https://github.com/PostHog/posthog/issues/46288
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

DROP_COLUMN_SQL = "ALTER TABLE {table} DROP COLUMN IF EXISTS {column}"

operations = [
    # 1. Drop the MV and Kafka table first (reverse order of creation)
    run_sql_with_exceptions(DROP_PERSONS_TABLE_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_KAFKA_PERSONS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    # 2. Drop columns from the writable table (Distributed engine)
    *[
        run_sql_with_exceptions(
            DROP_COLUMN_SQL.format(table=PERSONS_WRITABLE_TABLE, column=col),
            sharded=False,
            is_alter_on_replicated_table=False,
            node_roles=[NodeRole.INGESTION_SMALL],
        )
        for col in GROUP_KEY_COLUMNS
    ],
    # 3. Drop columns from the main person table (ReplicatedReplacingMergeTree)
    *[
        run_sql_with_exceptions(
            DROP_COLUMN_SQL.format(table=PERSONS_TABLE, column=col),
            sharded=False,
            is_alter_on_replicated_table=True,
            node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        )
        for col in GROUP_KEY_COLUMNS
    ],
    # 4. Recreate the Kafka table and MV without the columns
    run_sql_with_exceptions(KAFKA_PERSONS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(PERSONS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
]
