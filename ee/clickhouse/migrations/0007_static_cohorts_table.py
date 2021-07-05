from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import PERSON_STATIC_COHORT_TABLE_SQL


def operations(**kwargs):
    return [
        migrations.RunSQL(PERSON_STATIC_COHORT_TABLE_SQL),
    ]
