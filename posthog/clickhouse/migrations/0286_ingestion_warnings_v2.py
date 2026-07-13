from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ingestion_warnings.sql_v2 import (
    DISTRIBUTED_INGESTION_WARNINGS_V2_TABLE_SQL,
    INGESTION_WARNINGS_V2_DATA_TABLE_SQL,
    INGESTION_WARNINGS_V2_MV_SQL,
    KAFKA_INGESTION_WARNINGS_V2_TABLE_SQL,
)

operations = [
    # 1. Data table on aux (single shard, replicated)
    run_sql_with_exceptions(
        INGESTION_WARNINGS_V2_DATA_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 2. Kafka engine table on aux (consumes the clickhouse_ingestion_warnings topic via a v2 consumer group)
    run_sql_with_exceptions(
        KAFKA_INGESTION_WARNINGS_V2_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 3. MV on aux (Kafka -> data table, deriving structured dimensions from `details`)
    run_sql_with_exceptions(
        INGESTION_WARNINGS_V2_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 4. Distributed read table on aux and data nodes
    run_sql_with_exceptions(
        DISTRIBUTED_INGESTION_WARNINGS_V2_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
