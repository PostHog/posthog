from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.usage_ingestion.sql import (
    DISTRIBUTED_USAGE_RECORDS_TABLE_SQL,
    KAFKA_USAGE_RECORDS_TABLE_SQL,
    USAGE_RECORDS_DATA_TABLE_SQL,
    USAGE_RECORDS_MV_SQL,
    WRITABLE_USAGE_RECORDS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(USAGE_RECORDS_DATA_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DISTRIBUTED_USAGE_RECORDS_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(WRITABLE_USAGE_RECORDS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(KAFKA_USAGE_RECORDS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(USAGE_RECORDS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
]
