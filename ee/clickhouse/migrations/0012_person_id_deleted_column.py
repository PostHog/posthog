from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.person import KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL, PERSONS_DISTINCT_ID_TABLE_MV_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(f"DROP TABLE person_distinct_id_mv "),
    migrations.RunSQL(f"DROP TABLE kafka_person_distinct_id "),
    migrations.RunSQL(f"ALTER TABLE person_distinct_id  ADD COLUMN IF NOT EXISTS is_deleted Boolean DEFAULT 0"),
    migrations.RunSQL(KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL),
    migrations.RunSQL(PERSONS_DISTINCT_ID_TABLE_MV_SQL),
]
