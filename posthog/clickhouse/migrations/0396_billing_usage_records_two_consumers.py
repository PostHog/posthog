from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.usage_ingestion.billing_usage_records import (
    BILLING_USAGE_RECORDS_MV,
    BILLING_USAGE_RECORDS_MV_SQL,
    KAFKA_BILLING_USAGE_RECORDS_TABLE,
    KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL,
)
from posthog.run_mode import RunMode, run_mode

# A Kafka table takes its consumer settings only at creation, so this migration drops the view and
# the Kafka table and creates them again. The consumer group keeps its committed offsets, so the gap
# adds lag and the new consumers read every record that the old one did not commit. A record that a
# consumer reads twice has one identity, and sharded_billing_usage_records keeps one row for it.
# Only US changes its consumer settings, so the other deployments skip this migration.
operations = (
    [
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {BILLING_USAGE_RECORDS_MV}", node_roles=[NodeRole.INGESTION_SMALL]
        ),
        run_sql_with_exceptions(
            f"DROP TABLE IF EXISTS {KAFKA_BILLING_USAGE_RECORDS_TABLE}", node_roles=[NodeRole.INGESTION_SMALL]
        ),
        run_sql_with_exceptions(KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
        run_sql_with_exceptions(BILLING_USAGE_RECORDS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    ]
    if run_mode() is RunMode.CLOUD_US
    else []
)
