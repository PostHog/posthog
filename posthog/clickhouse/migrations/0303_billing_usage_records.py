from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.usage_ingestion.billing_usage_records import (
    BILLING_USAGE_RECORDS_DATA_TABLE_SQL,
    BILLING_USAGE_RECORDS_MV_SQL,
    DISTRIBUTED_BILLING_USAGE_RECORDS_TABLE_SQL,
    KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL,
    WRITABLE_BILLING_USAGE_RECORDS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(BILLING_USAGE_RECORDS_DATA_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DISTRIBUTED_BILLING_USAGE_RECORDS_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(WRITABLE_BILLING_USAGE_RECORDS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(BILLING_USAGE_RECORDS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
]
