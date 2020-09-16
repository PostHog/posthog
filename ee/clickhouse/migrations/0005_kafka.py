from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.elements import KAFKA_ELEMENTS_GROUP_TABLE_SQL, KAFKA_ELEMENTS_TABLE_SQL
from ee.clickhouse.sql.events import KAFKA_EVENTS_TABLE_SQL
from ee.clickhouse.sql.person import KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL, KAFKA_PERSONS_TABLE_SQL

operations = [
    migrations.RunSQL(KAFKA_EVENTS_TABLE_SQL),
    migrations.RunSQL(KAFKA_ELEMENTS_TABLE_SQL),
    migrations.RunSQL(KAFKA_ELEMENTS_GROUP_TABLE_SQL),
    migrations.RunSQL(KAFKA_PERSONS_TABLE_SQL),
    migrations.RunSQL(KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL),
]
