from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import (
    KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL,
    PERSON_DISTINCT_ID_OVERRIDES_MV_SQL,
    PERSON_DISTINCT_ID_OVERRIDES_TABLE,
)

operations = [
    run_sql_with_exceptions(KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL()),
    run_sql_with_exceptions(PERSON_DISTINCT_ID_OVERRIDES_MV_SQL(target_table=PERSON_DISTINCT_ID_OVERRIDES_TABLE)),
]
