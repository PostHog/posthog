from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.events import Events

operations = [migrations.migrations.CreateTable(Events)]
