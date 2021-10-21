from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import MATERIALIZED_PSQL_DB_BASE_SQL

operations = [migrations.RunSQL(MATERIALIZED_PSQL_DB_BASE_SQL)]
