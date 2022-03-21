from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.cohort import CREATE_COHORTPEOPLE_TABLE_SQL

operations = [migrations.RunSQL(CREATE_COHORTPEOPLE_TABLE_SQL())]
