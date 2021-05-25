from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import KAFKA_PERSONS_TABLE_SQL, PERSONS_TABLE_MV_SQL

operations = [
    migrations.RunSQL("DROP TABLE person_mv"),
    migrations.RunSQL("DROP TABLE kafka_person"),
    migrations.RunSQL("ALTER TABLE person ADD COLUMN IF NOT EXISTS is_deleted Boolean DEFAULT 0"),
    migrations.RunSQL(KAFKA_PERSONS_TABLE_SQL),
    migrations.RunSQL(PERSONS_TABLE_MV_SQL),
]
