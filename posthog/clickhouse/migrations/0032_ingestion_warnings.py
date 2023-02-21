from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ingestion_warnings.sql import (
    DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL,
    INGESTION_WARNINGS_DATA_TABLE_SQL,
    INGESTION_WARNINGS_MV_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(INGESTION_WARNINGS_DATA_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_INGESTION_WARNINGS_TABLE_SQL()),
    run_sql_with_exceptions(INGESTION_WARNINGS_MV_TABLE_SQL()),
]
