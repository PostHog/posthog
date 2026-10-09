from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_MV_SQL,
    FLAG_EVALUATIONS_MV_TABLE,
    FLAG_EVALUATIONS_TABLE,
    FLAG_EVALUATIONS_WRITABLE_TABLE,
    KAFKA_FLAG_EVALUATIONS_TABLE,
    KAFKA_FLAG_EVALUATIONS_TABLE_SQL,
)

# Adds person_properties, person_created_at and person_mode to the flag_evaluations family.
# posthog/models/flag_evaluations/sql.py carries the rationale.
#
# The ALTERs run before the Kafka table and MV are dropped, so a failed ALTER leaves the old MV
# ingesting. Its inserts omit the new columns, so each table fills their defaults. A shard replica
# that has not yet applied the sharded ALTER rejects a block from writable_flag_evaluations that
# carries the new columns, so a few inserts can fail and retry until it catches up. The recreate
# also applies the consumer settings that sql.py declares to any environment whose live table
# predates them.


def _add_person_columns(table: str) -> str:
    return (
        f"ALTER TABLE {table} "
        "ADD COLUMN IF NOT EXISTS person_properties String DEFAULT '{}' AFTER person_id, "
        "ADD COLUMN IF NOT EXISTS person_created_at DateTime64(3) AFTER person_properties, "
        "ADD COLUMN IF NOT EXISTS person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2) AFTER inserted_at"
    )


operations = [
    run_sql_with_exceptions(
        _add_person_columns(FLAG_EVALUATIONS_DATA_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        _add_person_columns(FLAG_EVALUATIONS_TABLE),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        _add_person_columns(FLAG_EVALUATIONS_WRITABLE_TABLE),
        node_roles=[NodeRole.INGESTION_MEDIUM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {FLAG_EVALUATIONS_MV_TABLE}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {KAFKA_FLAG_EVALUATIONS_TABLE}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        KAFKA_FLAG_EVALUATIONS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        FLAG_EVALUATIONS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
]
