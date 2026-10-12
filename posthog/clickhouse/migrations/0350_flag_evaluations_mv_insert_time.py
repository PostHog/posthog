from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_MV_TABLE, KAFKA_FLAG_EVALUATIONS_TABLE

# After this migration, flag_evaluations_mv stamps inserted_at with the time the
# view processes each row. posthog/models/flag_evaluations/sql.py carries the
# rationale. Rows written before this migration keep their old value.
#
# The migration uses MODIFY QUERY rather than drop-and-recreate, because only the
# SELECT changes. The MV stays attached to the Kafka table, so consumption does
# not stop.
#
# The SELECT is a copy of the one sql.py held for this migration, not an import.
# A node with this migration pending has the Kafka table of that time, so a column
# that a later migration adds to the sql.py SELECT does not exist there yet.
operations = [
    run_sql_with_exceptions(
        f"""ALTER TABLE {FLAG_EVALUATIONS_MV_TABLE} MODIFY QUERY
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    created_at,
    person_id,
    now64() AS inserted_at,
    _timestamp,
    _offset,
    _partition
FROM {settings.CLICKHOUSE_DATABASE}.{KAFKA_FLAG_EVALUATIONS_TABLE}""",
        node_roles=[NodeRole.INGESTION_MEDIUM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
