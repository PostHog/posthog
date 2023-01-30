from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ingestion_warnings.sql import (
    DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL,
    INGESTION_WARNINGS_MV_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_TABLE_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS ingestion_warnings_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_ingestion_warnings ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS ingestion_warnings ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_INGESTION_WARNINGS_TABLE_SQL()),
    run_sql_with_exceptions(INGESTION_WARNINGS_MV_TABLE_SQL()),
]
