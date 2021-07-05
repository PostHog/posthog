from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.events import EVENTS_TABLE_SQL


def operations(**kwargs):
    return [
        migrations.RunSQL(EVENTS_TABLE_SQL),
    ]
