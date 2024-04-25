from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import EVENTS_DATA_TABLE

EVENTS_TABLE_INSERTED_AT_PROJECTION_SQL = """
ALTER TABLE {table_name} ON CLUSTER {cluster}
ADD PROJECTION `inserted_at_batch_exports_projection` (
    SELECT
        _timestamp,
        created_at,
        distinct_id,
        elements_chain,
        event,
        inserted_at,
        person_created_at,
        person_id,
        person_properties,
        properties,
        team_id,
        timestamp,
        uuid
    ORDER BY (team_id, COALESCE(`inserted_at`, `_timestamp`), event, cityHash64(distinct_id), cityHash64(uuid))
)
""".format(table_name=EVENTS_DATA_TABLE(), cluster=settings.CLICKHOUSE_CLUSTER)

EVENTS_TABLE_INSERTED_AT_PROJECTION_MATERIALIZE_SQL = """
ALTER TABLE {table_name} ON CLUSTER {cluster}
MATERIALIZE PROJECTION `inserted_at_batch_exports_projection`
IN PARTITION '202404'
""".format(table_name=EVENTS_DATA_TABLE(), cluster=settings.CLICKHOUSE_CLUSTER)

operations = [
    run_sql_with_exceptions(EVENTS_TABLE_INSERTED_AT_PROJECTION_SQL),
    run_sql_with_exceptions(EVENTS_TABLE_INSERTED_AT_PROJECTION_MATERIALIZE_SQL),
]
