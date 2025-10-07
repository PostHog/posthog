from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import (
    KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL,
    PERSON_DISTINCT_ID2_MV_SQL,
    PERSON_DISTINCT_ID2_TABLE,
    PERSON_DISTINCT_ID2_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(PERSON_DISTINCT_ID2_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL()),
    run_sql_with_exceptions(PERSON_DISTINCT_ID2_MV_SQL(target_table=PERSON_DISTINCT_ID2_TABLE)),
]
