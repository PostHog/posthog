from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person_overrides.sql import (
    KAFKA_PERSON_OVERRIDES_TABLE_SQL,
    PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL,
    PERSON_OVERRIDES_CREATE_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(PERSON_OVERRIDES_CREATE_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_PERSON_OVERRIDES_TABLE_SQL),
    run_sql_with_exceptions(PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL),
]
