from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import COMMENT_DISTINCT_ID_COLUMN_SQL, PERSONS_DISTINCT_ID_TABLE_SQL, PERSONS_TABLE_SQL

operations = [
    migrations.RunSQL(PERSONS_TABLE_SQL()),
    migrations.RunSQL(PERSONS_DISTINCT_ID_TABLE_SQL()),
    # :TRICKY: This is only run on new installations, we use this to know to skip
    # posthog/async_migrations/migrations/0003_fill_person_distinct_id2.py
    # We would use table comments but can't due to clickhouse version limitations
    migrations.RunSQL(COMMENT_DISTINCT_ID_COLUMN_SQL()),
]
