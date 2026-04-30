from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.error_tracking.backend.embedding import (
    DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_WS_MV_SQL,
    KAFKA_DOCUMENT_EMBEDDINGS_WS_TABLE_SQL,
)
from products.error_tracking.backend.sql import (
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV_SQL,
    ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_MV_SQL,
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_TABLE_SQL,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_TABLE_SQL,
    WRITABLE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL,
    WRITABLE_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL,
)

# Migration to create WarpStream-shared Kafka engine tables for the topics moving from MSK
# to the warpstream-shared VC.
#
# Each pair coexists alongside its existing MSK Kafka engine table, reading from the same
# topic but via the warpstream_shared named collection with its own consumer group to avoid
# conflicts with the MSK table. Once produce traffic has shifted to shared, a follow-up
# migration drops the MSK side.
#
# Topics covered (CH-consumed; non-CH-consumed shared topics like `notification_events` and
# `signals_report_completed` don't need migrations):
# - clickhouse_document_embeddings
# - clickhouse_error_tracking_issue_fingerprint
# - clickhouse_error_tracking_fingerprint_issue_state
#
# CLOUD-ONLY: In non-cloud environments (CI, dev, hobby) there is only one ClickHouse
# node, so both the MSK and WS materialized views would consume the same Kafka topic
# and write to the same target table, doubling every row.

operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [
        # document_embeddings
        run_sql_with_exceptions(
            KAFKA_DOCUMENT_EMBEDDINGS_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            DOCUMENT_EMBEDDINGS_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # error_tracking_issue_fingerprint_overrides
        run_sql_with_exceptions(
            KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            WRITABLE_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # error_tracking_fingerprint_issue_state
        run_sql_with_exceptions(
            KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            WRITABLE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
    ]
)
