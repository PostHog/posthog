from infi.clickhouse_orm import migrations  # type: ignore

from ee.clickhouse.sql.events import EVENTS_TABLE_SQL

operations = [
    migrations.RunSQL(EVENTS_TABLE_SQL),
]
