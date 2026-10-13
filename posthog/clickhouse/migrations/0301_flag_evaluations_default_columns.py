from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import (
    DISTRIBUTED_FLAG_EVALUATIONS_TABLE_SQL,
    DROP_FLAG_EVALUATIONS_TABLE_SQL,
    FLAG_EVALUATIONS_TABLE,
    FLAG_EVALUATIONS_TABLE_SQL,
    FLAG_EVALUATIONS_WRITABLE_TABLE,
    WRITABLE_FLAG_EVALUATIONS_TABLE_SQL,
)

# Recreates flag_evaluations with its nine typed property columns as DEFAULT
# instead of MATERIALIZED, the assignable kind the property-removal rewrite
# resets by ALTER UPDATE. This clears the schema obstacle only: the rewrite
# machinery still sweeps just the events tables, so property removal does not
# reach this table yet (docs/internal/clickhouse-deletion-coverage.md).
# posthog/models/flag_evaluations/sql.py carries the full rationale.
#
# Drop-and-recreate rather than ALTER, as in 0297: nothing produces to the topic
# yet, so the family is empty everywhere and this must land before the producer
# does. Unlike 0297 the Kafka table and the MV stay untouched, because their DDL
# does not change; only the sharded table's column kind does. The two Distributed
# fronts render identical DDL too, but recreating them is free while the family
# is empty and reconciles any environment whose fronts drifted from the repo
# rendering. The sharded table is replicated, so its drop carries SYNC to clear
# ZooKeeper metadata before the recreate; the Distributed fronts drop plain.
operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {FLAG_EVALUATIONS_TABLE}",
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {FLAG_EVALUATIONS_WRITABLE_TABLE}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        DROP_FLAG_EVALUATIONS_TABLE_SQL(),
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
]
