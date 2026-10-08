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
# The sharded table and both Distributed tables take an ALTER, which only changes metadata. They
# change while the old MV keeps consuming. Its inserts omit the new columns, so each table fills
# their defaults. The sharded table changes before writable_flag_evaluations. A replica that has not
# yet applied the sharded ALTER from its replication queue rejects a block that carries the columns,
# so a few inserts can fail and retry until it catches up. A Kafka engine table cannot ALTER its
# columns, so it is dropped and recreated with its MV after the ALTERs succeed. If an ALTER fails,
# the old MV keeps ingesting. The recreated Kafka table keeps its consumer group, so consumption
# resumes from the committed offsets. The recreate also applies the consumer settings that sql.py
# declares to any environment whose live table predates them.


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
