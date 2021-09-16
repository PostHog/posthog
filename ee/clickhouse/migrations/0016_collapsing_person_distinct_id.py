from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import *
from posthog.settings import CLICKHOUSE_CLUSTER

TEMPORARY_TABLE_NAME = "person_distinct_id_tmp_migration_0016"

operations = [
    migrations.RunSQL(PERSONS_DISTINCT_ID_TABLE_SQL.replace(PERSONS_DISTINCT_ID_TABLE, TEMPORARY_TABLE_NAME, 1)),
    migrations.RunSQL(f"DROP TABLE person_distinct_id_mv ON CLUSTER {CLICKHOUSE_CLUSTER}"),
    migrations.RunSQL(f"DROP TABLE kafka_person_distinct_id ON CLUSTER {CLICKHOUSE_CLUSTER}"),
    migrations.RunSQL(
        f"""
        INSERT INTO {TEMPORARY_TABLE_NAME} (distinct_id, person_id, team_id, _sign, _timestamp, _offset)
        SELECT
            distinct_id,
            person_id,
            team_id,
            if(is_deleted==0, 1, -1) as _sign,
            _timestamp,
            _offset
        FROM {PERSONS_DISTINCT_ID_TABLE}
    """
    ),
    migrations.RunSQL(
        f"""
        RENAME TABLE
            {CLICKHOUSE_DATABASE}.{PERSONS_DISTINCT_ID_TABLE} to {CLICKHOUSE_DATABASE}.person_distinct_id_backup,
            {CLICKHOUSE_DATABASE}.{TEMPORARY_TABLE_NAME} to {CLICKHOUSE_DATABASE}.{PERSONS_DISTINCT_ID_TABLE}
        ON CLUSTER {CLICKHOUSE_CLUSTER}
    """
    ),
    migrations.RunSQL(KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL),
    migrations.RunSQL(PERSONS_DISTINCT_ID_TABLE_MV_SQL),
]
