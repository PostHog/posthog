from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Drop MSK Kafka engine tables and their materialized views for topics that are
# no longer actively produced to, or whose functionality has been superseded.
#
# These tables still exist on the ingestion layer using the MSK named collection
# but serve no purpose:
#
# - plugin_log_entries: No producer writes to this topic anymore.
# - app_metrics (v1): Superseded by app_metrics2; no producer writes to v1.
# - events_dead_letter_queue: No longer needed.
# - duplicate_events: No longer needed.
# - error_tracking_issue_fingerprint_embeddings: Experimental table replaced by
#   the general-purpose document_embeddings tables in migration 0155. The 0155
#   drop ran on NodeRole.DATA but the tables were created on INGESTION_SMALL,
#   so the Kafka table and MV survived on ingestion nodes.
#
# Order: drop the MV first so it stops feeding the writable target, then drop
# the Kafka engine table. `IF EXISTS` keeps the migration idempotent.
#
# CLOUD-ONLY: In non-cloud environments (CI, dev, hobby) some of these tables
# may be the only consumer for their topics, so we guard the drops.

operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [
        # plugin_log_entries (INGESTION_SMALL — moved here by migration 0152)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS plugin_log_entries_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_plugin_log_entries",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # app_metrics v1 (INGESTION_SMALL — moved here by migration 0157)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS app_metrics_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_app_metrics",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # events_dead_letter_queue (INGESTION_SMALL — moved here by migration 0157)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS events_dead_letter_queue_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_events_dead_letter_queue",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # duplicate_events (INGESTION_SMALL — created by migration 0156)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS duplicate_events_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_duplicate_events",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # error_tracking_issue_fingerprint_embeddings (INGESTION_SMALL — created
        # by migration 0153, drop in 0155 missed ingestion nodes because it
        # ran on NodeRole.DATA instead of INGESTION_SMALL)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS error_tracking_issue_fingerprint_embeddings_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_error_tracking_issue_fingerprint_embeddings",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS writable_error_tracking_issue_fingerprint_embeddings",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
    ]
)
