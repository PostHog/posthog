from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import KAFKA_PERSONS_TABLE_SQL, PERSONS_TABLE_MV_SQL


def operations(is_backup_host):
    if is_backup_host:
        return [
            migrations.RunSQL("ALTER TABLE person ADD COLUMN IF NOT EXISTS is_deleted Boolean DEFAULT 0"),
        ]
    else:
        return [
            migrations.RunSQL("DROP TABLE person_mv"),
            migrations.RunSQL("DROP TABLE kafka_person"),
            migrations.RunSQL("ALTER TABLE person ADD COLUMN IF NOT EXISTS is_deleted Boolean DEFAULT 0"),
            migrations.RunSQL(KAFKA_PERSONS_TABLE_SQL),
            migrations.RunSQL(PERSONS_TABLE_MV_SQL),
        ]
