from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.sql import (
    ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_MV_SQL,
    ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL,
    ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE_SQL,
    KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    run_sql_with_exceptions(
        ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
]
