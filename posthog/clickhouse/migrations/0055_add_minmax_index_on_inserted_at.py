from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import EVENTS_TABLE_INSERTED_AT_INDEX_SQL, EVENTS_TABLE_MATERIALIZE_INSERTED_AT_INDEX_SQL

operations = [
    run_sql_with_exceptions(EVENTS_TABLE_INSERTED_AT_INDEX_SQL),
    run_sql_with_exceptions(EVENTS_TABLE_MATERIALIZE_INSERTED_AT_INDEX_SQL),
]
