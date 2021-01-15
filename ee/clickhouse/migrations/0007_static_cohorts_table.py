from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import KAFKA_PERSON_STATIC_COHORT_TABLE_SQL, PERSON_STATIC_COHORT_TABLE_SQL

operations = [
    migrations.RunSQL(PERSON_STATIC_COHORT_TABLE_SQL),
]
