from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ingestion_warnings.sql import (
    DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL,
    INGESTION_WARNINGS_DATA_TABLE_SQL,
    INGESTION_WARNINGS_MV_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_TABLE_SQL,
)

# Identical to 0032_ingestion_warnings, just need to re-run it again, as the tables are missing in some envs

operations = [
    run_sql_with_exceptions(INGESTION_WARNINGS_DATA_TABLE_SQL(), sharded=True, node_roles=NodeRole.DATA),
    run_sql_with_exceptions(DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL(), node_roles=[NodeRole.COORDINATOR]),
    run_sql_with_exceptions(KAFKA_INGESTION_WARNINGS_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(
        INGESTION_WARNINGS_MV_TABLE_SQL(target_table="ingestion_warnings"), node_roles=NodeRole.DATA
    ),
]
