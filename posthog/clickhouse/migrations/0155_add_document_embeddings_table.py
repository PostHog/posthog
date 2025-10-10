from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.error_tracking.embedding import (
    DOCUMENT_EMBEDDINGS_MV_SQL,
    DOCUMENT_EMBEDDINGS_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL,
    KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL,
)

# These tables were used in an experiment, and then replaced with the general purpose tables defined above
ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE = "error_tracking_issue_fingerprint_embeddings"
ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE = f"writable_{ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE}"
KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE = f"kafka_{ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE}"
ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_MV = f"{ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE}_mv"


operations = [
    run_sql_with_exceptions(DOCUMENT_EMBEDDINGS_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DOCUMENT_EMBEDDINGS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    # Order matters here I think - MV first, then kafka, then writable, then readable. Choice of node_roles
    # SETTINGS based on 0146_drop_session_replay_events_v2_test_table.py
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_MV}"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE}"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS {KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE}"),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE} SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
