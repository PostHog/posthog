from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import PERSONS_DISTINCT_ID_TABLE_SQL, PERSONS_TABLE_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(PERSONS_TABLE_SQL()),
    migrations.RunSQL(PERSONS_DISTINCT_ID_TABLE_SQL()),
    # :TRICKY: This is only run on new installations, we use this to know to skip
    # posthog/async_migrations/migrations/0003_fill_person_distinct_id2.py
    # We would use table comments but can't due to clickhouse version limitations
    migrations.RunSQL(
        f"""
        ALTER TABLE person_distinct_id ON CLUSTER {CLICKHOUSE_CLUSTER}
        COMMENT COLUMN distinct_id 'skip_0003_fill_person_distinct_id2'
    """
    ),
]
