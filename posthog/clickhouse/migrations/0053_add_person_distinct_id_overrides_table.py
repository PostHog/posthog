from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL

operations = [
    run_sql_with_exceptions(PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL()),
]
