from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_MV_SELECT_SQL, FLAG_EVALUATIONS_MV_TABLE

# This migration changes flag_evaluations_mv to stamp inserted_at with the time
# the view processes each row, instead of the Kafka message time.
# posthog/models/flag_evaluations/sql.py carries the rationale. Rows written
# before this migration keep their old value.
#
# MODIFY QUERY rather than drop-and-recreate, because only the SELECT changes. The
# MV stays attached to the Kafka table, so consumption does not stop.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {FLAG_EVALUATIONS_MV_TABLE} MODIFY QUERY\n{FLAG_EVALUATIONS_MV_SELECT_SQL()}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
