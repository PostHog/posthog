from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.sql import (
    ERROR_TRACKING_EVENTS_TEST_MV_SQL,
    ERROR_TRACKING_EVENTS_TEST_TABLE_SQL,
    KAFKA_ERROR_TRACKING_EVENTS_TEST_TABLE_SQL,
    WRITABLE_ERROR_TRACKING_EVENTS_TEST_TABLE_SQL,
)

operations = [
    # Data table runs on DATA nodes
    run_sql_with_exceptions(
        ERROR_TRACKING_EVENTS_TEST_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Writable distributed table on ingestion layer (routes writes to data table)
    run_sql_with_exceptions(
        WRITABLE_ERROR_TRACKING_EVENTS_TEST_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # Kafka table and MV on ingestion layer
    run_sql_with_exceptions(
        KAFKA_ERROR_TRACKING_EVENTS_TEST_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        ERROR_TRACKING_EVENTS_TEST_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
