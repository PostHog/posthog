from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.channel_type.sql import (
    CHANNEL_DEFINITION_TABLE_SQL,
    CHANNEL_DEFINITIONS_DATA_SQL,
    CHANNEL_DEFINITION_DICTIONARY_SQL,
)

operations = [
    run_sql_with_exceptions(CHANNEL_DEFINITION_TABLE_SQL),
    run_sql_with_exceptions(CHANNEL_DEFINITIONS_DATA_SQL),
    run_sql_with_exceptions(CHANNEL_DEFINITION_DICTIONARY_SQL),
]
