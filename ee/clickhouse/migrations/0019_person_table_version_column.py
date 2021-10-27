from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import *
from posthog.settings import CLICKHOUSE_CLUSTER

TEMPORARY_TABLE_NAME = "person_tmp_migration_0019"

operations = [
    migrations.RunSQL(PERSONS_TABLE_SQL.replace(PERSONS_TABLE, TEMPORARY_TABLE_NAME, 1)),
    migrations.RunSQL(f"DROP TABLE person_mv ON CLUSTER {CLICKHOUSE_CLUSTER}"),
    migrations.RunSQL(f"DROP TABLE kafka_person ON CLUSTER {CLICKHOUSE_CLUSTER}"),
    migrations.RunSQL(
        f"""
        INSERT INTO {TEMPORARY_TABLE_NAME} (id, team_id, created_at, properties, is_identified, is_deleted, version, _partition, _timestamp, _offset)
        SELECT
            id,
            team_id,
            created_at,
            properties,
            is_identified,
            is_deleted,
            0,
            0,
            _timestamp,
            _offset
        FROM {PERSONS_TABLE}
    """
    ),
    migrations.RunSQL(
        f"""
        RENAME TABLE
            {CLICKHOUSE_DATABASE}.{PERSONS_TABLE} to {CLICKHOUSE_DATABASE}.person_backup_0019,
            {CLICKHOUSE_DATABASE}.{TEMPORARY_TABLE_NAME} to {CLICKHOUSE_DATABASE}.{PERSONS_TABLE}
        ON CLUSTER {CLICKHOUSE_CLUSTER}
    """
    ),
    migrations.RunSQL(KAFKA_PERSONS_TABLE_SQL),
    migrations.RunSQL(PERSONS_TABLE_MV_SQL),
]
