from infi.clickhouse_orm import migrations

from posthog.models.cohort.sql import CREATE_COHORT_ACTORS_TABLE_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(f"DROP TABLE IF EXISTS cohort_actors ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(CREATE_COHORT_ACTORS_TABLE_SQL()),
]
