from infi.clickhouse_orm import migrations

from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE_SQL

operations = [
    migrations.RunSQL(PERSON_STATIC_COHORT_TABLE_SQL()),
]
