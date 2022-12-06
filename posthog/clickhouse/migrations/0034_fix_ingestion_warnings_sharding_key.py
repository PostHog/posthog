from infi.clickhouse_orm import migrations

from posthog.models.ingestion_warnings.sql import (
    DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL,
    INGESTION_WARNINGS_MV_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_TABLE_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(f"DROP TABLE IF EXISTS ingestion_warnings_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE IF EXISTS kafka_ingestion_warnings ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE IF EXISTS ingestion_warnings ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_INGESTION_WARNINGS_TABLE_SQL()),
    migrations.RunSQL(INGESTION_WARNINGS_MV_TABLE_SQL()),
]
