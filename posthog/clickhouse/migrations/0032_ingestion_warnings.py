from infi.clickhouse_orm import migrations

from posthog.models.ingestion_warnings.sql import (
    DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL,
    INGESTION_WARNINGS_DATA_TABLE_SQL,
    INGESTION_WARNINGS_MV_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_TABLE_SQL,
)

operations = [
    migrations.RunSQL(INGESTION_WARNINGS_DATA_TABLE_SQL()),
    migrations.RunSQL(DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_INGESTION_WARNINGS_TABLE_SQL()),
    migrations.RunSQL(INGESTION_WARNINGS_MV_TABLE_SQL()),
]
