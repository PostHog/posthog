from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.events import MAT_EVENT_PROP_TABLE_SQL, MAT_EVENTS_WITH_PROPS_TABLE_SQL

operations = [
    migrations.RunSQL(MAT_EVENTS_WITH_PROPS_TABLE_SQL),
    migrations.RunSQL(MAT_EVENT_PROP_TABLE_SQL),
]
