from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import (
    DISTRIBUTED_FLAG_EVALUATIONS_TABLE_SQL,
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_MV_SQL,
    FLAG_EVALUATIONS_MV_TABLE,
    FLAG_EVALUATIONS_TABLE,
    FLAG_EVALUATIONS_TABLE_SQL,
    FLAG_EVALUATIONS_WRITABLE_TABLE,
    KAFKA_FLAG_EVALUATIONS_TABLE,
    KAFKA_FLAG_EVALUATIONS_TABLE_SQL,
    WRITABLE_FLAG_EVALUATIONS_TABLE_SQL,
)

# Reshapes flag_evaluations before launch, replacing the typed flag columns 0292
# created. posthog/models/flag_evaluations/sql.py carries the rationale for the
# shape.
#
# Drop-and-recreate rather than ALTER: nothing produces to the topic yet, so every
# table in the family is empty; recreating from the canonical column template can't
# drift from what a fresh install gets out of schema.py; and it avoids DROP COLUMN
# mutations, which can get stuck and block releases. The sharded table is
# replicated, so its drop carries SYNC to clear ZooKeeper metadata before the
# recreate. The Distributed, Kafka, and MV objects are not replicated and drop
# plain.
#
# Drops run in reverse dependency order (MV → its Kafka source → the Distributed
# fronts → storage); recreates mirror 0292's order and node roles.
operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {FLAG_EVALUATIONS_MV_TABLE}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {KAFKA_FLAG_EVALUATIONS_TABLE}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {FLAG_EVALUATIONS_TABLE}",
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {FLAG_EVALUATIONS_WRITABLE_TABLE}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {FLAG_EVALUATIONS_DATA_TABLE} SYNC",
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        FLAG_EVALUATIONS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        WRITABLE_FLAG_EVALUATIONS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_FLAG_EVALUATIONS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
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
