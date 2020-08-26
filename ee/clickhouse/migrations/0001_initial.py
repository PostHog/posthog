from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.events import EVENT_SQL

operations = [
    migrations.RunSQL(EVENT_SQL),
]
