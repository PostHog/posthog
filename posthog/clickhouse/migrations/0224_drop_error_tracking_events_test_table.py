from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.sql import (
    DROP_ERROR_TRACKING_EVENTS_TEST_KAFKA_TABLE_SQL,
    DROP_ERROR_TRACKING_EVENTS_TEST_MV_SQL,
    DROP_ERROR_TRACKING_EVENTS_TEST_TABLE_SQL,
    DROP_ERROR_TRACKING_EVENTS_TEST_WRITABLE_TABLE_SQL,
)

# Drop the test tables created in migration 0221 for validating the error tracking
# Node ingestion pipeline. The pipeline is now in production and outputs to the
# main clickhouse_events_json topic, so these tables are no longer needed.
#
# Drop order: MV first (stops writes), then kafka table, writable table, data table.

operations = [
    run_sql_with_exceptions(
        DROP_ERROR_TRACKING_EVENTS_TEST_MV_SQL,
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        DROP_ERROR_TRACKING_EVENTS_TEST_KAFKA_TABLE_SQL,
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        DROP_ERROR_TRACKING_EVENTS_TEST_WRITABLE_TABLE_SQL,
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        DROP_ERROR_TRACKING_EVENTS_TEST_TABLE_SQL,
        node_roles=[NodeRole.DATA],
    ),
]
