from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import *
from posthog.settings import CLICKHOUSE_CLUSTER

TEMPORARY_TABLE_NAME = "person_tmp_migration_0019"

operations = [
    migrations.RunSQL(
        "ALTER TABLE person ADD COLUMN IF NOT EXISTS version UInt64, ADD COLUMN IF NOT EXISTS _partition UInt32"
    ),
    migrations.RunSQL(PERSONS_TABLE_SQL.replace(PERSONS_TABLE, TEMPORARY_TABLE_NAME, 1)),
    migrations.RunSQL(f"DROP TABLE person_mv ON CLUSTER {CLICKHOUSE_CLUSTER}"),
    migrations.RunSQL(f"DROP TABLE kafka_person ON CLUSTER {CLICKHOUSE_CLUSTER}"),
    # Check partition names with: `SELECT partition FROM system.parts WHERE table = 'person' and active = 1 GROUP BY partition;`
    # The persons table currently doesn't have a PARTITION BY clause so tuple() is the default
    migrations.RunSQL(f"ALTER TABLE {TEMPORARY_TABLE_NAME} ATTACH PARTITION tuple() FROM person"),
    migrations.RunSQL(
        f"""
        RENAME TABLE
            {CLICKHOUSE_DATABASE}.{PERSONS_TABLE} to {CLICKHOUSE_DATABASE}.person_backup_0019,
            {CLICKHOUSE_DATABASE}.{TEMPORARY_TABLE_NAME} to {CLICKHOUSE_DATABASE}.{PERSONS_TABLE}
        ON CLUSTER {CLICKHOUSE_CLUSTER}
    """
    ),
    # migrations.RunSQL("OPTIMIZE TABLE person FINAL") # TODO: Investigate - do we need this?
    migrations.RunSQL(KAFKA_PERSONS_TABLE_SQL),
    migrations.RunSQL(PERSONS_TABLE_MV_SQL),
]
