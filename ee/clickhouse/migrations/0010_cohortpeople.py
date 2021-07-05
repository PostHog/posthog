from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.cohort import CREATE_COHORTPEOPLE_TABLE_SQL


def operations(**kwargs):
    return [migrations.RunSQL(CREATE_COHORTPEOPLE_TABLE_SQL)]
