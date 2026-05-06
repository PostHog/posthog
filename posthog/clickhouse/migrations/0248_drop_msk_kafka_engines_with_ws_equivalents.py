from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Drop MSK Kafka engine tables and their materialized views for every topic that
# already has a WarpStream (`_ws`) consumer in place. Each pair listed here was
# created by an earlier migration (0227, 0229, 0232, 0234/0241, 0242, 0245, 0246,
# 0247) that put the `_ws` Kafka table + MV alongside the existing MSK pair so
# both could consume the same topic via different consumer groups during the
# migration window. Now that produce traffic has shifted, the MSK side is
# redundant and is removed here.
#
# Order: drop the MV first so it stops feeding the writable target, then drop
# the Kafka engine table. `IF EXISTS` keeps the migration idempotent.
#
# CLOUD-ONLY: Mirrors the cloud guard used by the `_ws` create migrations from
# 0232 onward. In non-cloud environments (CI, dev, hobby) there is a single
# ClickHouse node and the MSK pipeline is the only consumer for several of
# these topics, so dropping it would break ingestion locally.
#
# Special cases:
# - log_entries: the active MSK consumer is `kafka_log_entries_v3` + the MV
#   `log_entries_v3_mv` (see migration 0157). The original `log_entries_mv` /
#   `kafka_log_entries` from migration 0049 are not the live consumers.
# - error_tracking_fingerprint_issue_state: the MSK pair was created on
#   NodeRole.AUX (migration 0226). The `_ws` pair was added on
#   NodeRole.INGESTION_SMALL by migration 0247, so both node roles are targeted
#   for the drop in case the MSK pair was also placed on INGESTION_SMALL
#   out-of-band.

operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [
        # log_entries (INGESTION_SMALL — `_v3` is the live MSK consumer)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS log_entries_v3_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_log_entries_v3",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # app_metrics2 (INGESTION_MEDIUM)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS app_metrics2_mv",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_app_metrics2",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        # tophog (INGESTION_MEDIUM)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS tophog_mv",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_tophog",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        # precalculated_events (INGESTION_MEDIUM)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS precalculated_events_mv",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_precalculated_events",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        # precalculated_person_properties (INGESTION_MEDIUM)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS precalculated_person_properties_mv",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_precalculated_person_properties",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        # events_json (INGESTION_EVENTS)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS events_json_mv",
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_events_json",
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        # groups (INGESTION_SMALL)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS groups_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_groups",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # person (INGESTION_SMALL)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS person_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_person",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # person_distinct_id2 (INGESTION_SMALL)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS person_distinct_id2_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_person_distinct_id2",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # person_distinct_id_overrides (INGESTION_SMALL)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS person_distinct_id_overrides_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_person_distinct_id_overrides",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # ai_events_json (AI_EVENTS satellite cluster)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS ai_events_json_mv",
            node_roles=[NodeRole.AI_EVENTS],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_ai_events_json",
            node_roles=[NodeRole.AI_EVENTS],
        ),
        # heatmaps (INGESTION_MEDIUM)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS heatmaps_mv",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_heatmaps",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        # ingestion_warnings (INGESTION_SMALL)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS ingestion_warnings_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_ingestion_warnings",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # cohort_membership (INGESTION_MEDIUM)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS cohort_membership_mv",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_cohort_membership",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        # session_replay_events (INGESTION_SMALL)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS session_replay_events_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_session_replay_events",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # session_replay_features (INGESTION_MEDIUM)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS session_replay_features_mv",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_session_replay_features",
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        # document_embeddings (INGESTION_SMALL)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS posthog_document_embeddings_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_posthog_document_embeddings",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # error_tracking_issue_fingerprint_overrides (INGESTION_SMALL)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS error_tracking_issue_fingerprint_overrides_mv",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_error_tracking_issue_fingerprint_overrides",
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # error_tracking_fingerprint_issue_state (AUX + INGESTION_SMALL — see header)
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS error_tracking_fingerprint_issue_state_mv",
            node_roles=[NodeRole.AUX, NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_error_tracking_fingerprint_issue_state",
            node_roles=[NodeRole.AUX, NodeRole.INGESTION_SMALL],
        ),
    ]
)
