from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import PERSONS_DISTINCT_ID_TABLE_SQL, PERSONS_TABLE_SQL

operations = [migrations.RunSQL(PERSONS_TABLE_SQL), migrations.RunSQL(PERSONS_DISTINCT_ID_TABLE_SQL)]
