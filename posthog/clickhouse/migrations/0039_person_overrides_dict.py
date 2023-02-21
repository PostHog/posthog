from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person_overrides.sql import PERSON_OVERRIDES_CREATE_DICTIONARY_SQL

operations = [
    run_sql_with_exceptions(PERSON_OVERRIDES_CREATE_DICTIONARY_SQL),
]
