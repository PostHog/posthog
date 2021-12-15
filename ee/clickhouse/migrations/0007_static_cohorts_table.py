from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import PERSON_STATIC_COHORT_TABLE_SQL

operations = [
    migrations.RunSQL(PERSON_STATIC_COHORT_TABLE_SQL()),
]
