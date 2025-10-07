from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ingestion_warnings.sql import (
    DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL,
    INGESTION_WARNINGS_MV_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_TABLE_SQL,
)
<<<<<<< Updated upstream
=======
from django.conf import settings
>>>>>>> Stashed changes

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS ingestion_warnings_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS kafka_ingestion_warnings ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
    ),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS ingestion_warnings ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_INGESTION_WARNINGS_TABLE_SQL()),
    run_sql_with_exceptions(INGESTION_WARNINGS_MV_TABLE_SQL()),
]
