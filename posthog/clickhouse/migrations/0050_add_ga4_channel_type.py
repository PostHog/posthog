from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.channel_type.sql import (
    GA4_CHANNEL_DEFINITION_TABLE_SQL,
    GA_CHANNEL_DEFINITIONS_DATA_SQL,
    GA4_CHANNEL_DEFINITION_DICTIONARY_SQL,
)

operations = [
    run_sql_with_exceptions(GA4_CHANNEL_DEFINITION_TABLE_SQL),
    run_sql_with_exceptions(GA_CHANNEL_DEFINITIONS_DATA_SQL),
    run_sql_with_exceptions(GA4_CHANNEL_DEFINITION_DICTIONARY_SQL),
]
