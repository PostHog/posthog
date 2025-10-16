from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import KAFKA_PERSONS_TABLE_SQL, PERSONS_TABLE, PERSONS_TABLE_MV_SQL

operations = [
    run_sql_with_exceptions(f"DROP TABLE person_mv"),
    run_sql_with_exceptions(f"DROP TABLE kafka_person"),
    run_sql_with_exceptions(f"ALTER TABLE person DROP COLUMN IF EXISTS distinct_ids"),
    run_sql_with_exceptions(KAFKA_PERSONS_TABLE_SQL()),
    run_sql_with_exceptions(PERSONS_TABLE_MV_SQL(target_table=PERSONS_TABLE)),
]
