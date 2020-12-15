from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.events import EVENT_PROP_TABLE_SQL, EVENTS_WITH_PROPS_TABLE_SQL

operations = [
    migrations.RunSQL(EVENTS_WITH_PROPS_TABLE_SQL),
    migrations.RunSQL(EVENT_PROP_TABLE_SQL),
]
