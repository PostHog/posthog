"""
Drop person_properties and group0_properties through group4_properties from the
flag_evaluations table family.

No Insight or Hog function in either production region breaks down or filters on
either blob. The ClickHouse team already dropped these columns directly on both
prod clusters, so this migration brings dev, local, and the codebase schema in
line with that; the ALTER operations are a no-op on prod, and dropping and
recreating the MV and Kafka table reapplies the same definition prod already has.

See posthog/models/flag_evaluations/sql.py for the full column rationale.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import (
    DROP_FLAG_EVALUATIONS_MV_SQL,
    DROP_KAFKA_FLAG_EVALUATIONS_TABLE_SQL,
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_MV_SQL,
    FLAG_EVALUATIONS_TABLE,
    FLAG_EVALUATIONS_WRITABLE_TABLE,
    KAFKA_FLAG_EVALUATIONS_TABLE_SQL,
)

DROPPED_COLUMNS = [
    "person_properties",
    "group0_properties",
    "group1_properties",
    "group2_properties",
    "group3_properties",
    "group4_properties",
]

_DROP_COLUMNS_CLAUSE = ", ".join(f"DROP COLUMN IF EXISTS {column}" for column in DROPPED_COLUMNS)


def _drop_columns_sql(table: str) -> str:
    return f"ALTER TABLE {table} {_DROP_COLUMNS_CLAUSE}"


operations = [
    # 1. Drop the MV and Kafka table first: the Kafka engine does not support
    # ALTER ... DROP COLUMN, so they must be recreated rather than altered.
    run_sql_with_exceptions(DROP_FLAG_EVALUATIONS_MV_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(DROP_KAFKA_FLAG_EVALUATIONS_TABLE_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
    # 2. Drop the columns from the writable Distributed table (ingestion layer)
    run_sql_with_exceptions(
        _drop_columns_sql(FLAG_EVALUATIONS_WRITABLE_TABLE),
        node_roles=[NodeRole.INGESTION_MEDIUM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # 3. Drop the columns from the sharded storage table (main cluster, one op per shard)
    run_sql_with_exceptions(
        _drop_columns_sql(FLAG_EVALUATIONS_DATA_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # 4. Drop the columns from the Distributed read table (main cluster)
    run_sql_with_exceptions(
        _drop_columns_sql(FLAG_EVALUATIONS_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # 5. Recreate the Kafka table and MV without the dropped columns
    run_sql_with_exceptions(KAFKA_FLAG_EVALUATIONS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(FLAG_EVALUATIONS_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
