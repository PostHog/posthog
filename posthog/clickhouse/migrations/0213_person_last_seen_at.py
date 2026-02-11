from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import KAFKA_PERSONS_TABLE_SQL, PERSONS_TABLE, PERSONS_TABLE_MV_SQL
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS person_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_person ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(
        f"ALTER TABLE person ON CLUSTER '{CLICKHOUSE_CLUSTER}' ADD COLUMN IF NOT EXISTS last_seen_at Nullable(DateTime64)"
    ),
    run_sql_with_exceptions(KAFKA_PERSONS_TABLE_SQL()),
    run_sql_with_exceptions(PERSONS_TABLE_MV_SQL(target_table=PERSONS_TABLE)),
]
