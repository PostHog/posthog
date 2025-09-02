from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import COMMENT_DISTINCT_ID_COLUMN_SQL, PERSONS_DISTINCT_ID_TABLE_SQL, PERSONS_TABLE_SQL

operations = [
    run_sql_with_exceptions(PERSONS_TABLE_SQL()),
    run_sql_with_exceptions(PERSONS_DISTINCT_ID_TABLE_SQL()),
    # :TRICKY: This is only run on new installations, we use this to know to skip
    # posthog/async_migrations/migrations/0003_fill_person_distinct_id2.py
    # We would use table comments but can't due to clickhouse version limitations
    run_sql_with_exceptions(COMMENT_DISTINCT_ID_COLUMN_SQL()),
]
