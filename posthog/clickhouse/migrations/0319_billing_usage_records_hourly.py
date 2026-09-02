from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.usage_ingestion.billing_usage_records import (
    BILLING_USAGE_RECORDS_HOURLY_DATA_TABLE_SQL,
    DISTRIBUTED_BILLING_USAGE_RECORDS_HOURLY_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        BILLING_USAGE_RECORDS_HOURLY_DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
    run_sql_with_exceptions(DISTRIBUTED_BILLING_USAGE_RECORDS_HOURLY_TABLE_SQL(), node_roles=[NodeRole.DATA]),
]
