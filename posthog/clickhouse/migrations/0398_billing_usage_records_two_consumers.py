from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.usage_ingestion.billing_usage_records import (
    BILLING_USAGE_RECORDS_MV_SQL,
    KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL,
)

# A Kafka table takes its settings only at creation. The US and EU nodes already run the settings
# of KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL, so this migration does not drop the table or the view.
# Both statements use IF NOT EXISTS and change nothing where the table and the view exist.
operations = [
    run_sql_with_exceptions(KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(BILLING_USAGE_RECORDS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
]
