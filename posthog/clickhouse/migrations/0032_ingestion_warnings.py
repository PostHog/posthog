from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ingestion_warnings.sql import (
    DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL,
    INGESTION_WARNINGS_DATA_TABLE_SQL,
    INGESTION_WARNINGS_MV_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(INGESTION_WARNINGS_DATA_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    # coordinator concept was added much later, there's a separate migration fixing it
    run_sql_with_exceptions(DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(KAFKA_INGESTION_WARNINGS_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(
        INGESTION_WARNINGS_MV_TABLE_SQL(target_table="ingestion_warnings"), node_roles=NodeRole.DATA
    ),
]
