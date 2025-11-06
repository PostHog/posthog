from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL, PERSONS_DISTINCT_ID_TABLE_MV_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    run_sql_with_exceptions(f"DROP TABLE person_distinct_id_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE kafka_person_distinct_id ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(
        f"ALTER TABLE person_distinct_id ON CLUSTER '{CLICKHOUSE_CLUSTER}' ADD COLUMN IF NOT EXISTS is_deleted Int8 DEFAULT 0"
    ),
    run_sql_with_exceptions(KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL()),
    run_sql_with_exceptions(PERSONS_DISTINCT_ID_TABLE_MV_SQL()),
]
