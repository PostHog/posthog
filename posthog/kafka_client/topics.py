# Keep this in sync with plugin-server/src/config/kafka-topics.ts

from django.conf import settings

KAFKA_EVENTS_JSON = f"{settings.KAFKA_PREFIX}clickhouse_events_json{settings.SUFFIX}"
KAFKA_EXCEPTIONS_INGESTION = f"{settings.KAFKA_PREFIX}exceptions_ingestion{settings.SUFFIX}"
KAFKA_EVENTS_PLUGIN_INGESTION = settings.get_from_env(
    "KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC", f"{settings.KAFKA_PREFIX}events_plugin_ingestion{settings.SUFFIX}"
)
KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW = settings.get_from_env(
    "KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW_TOPIC",
    f"{settings.KAFKA_PREFIX}events_plugin_ingestion_overflow{settings.SUFFIX}",
)
KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL = settings.get_from_env(
    "KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL_TOPIC",
    f"{settings.KAFKA_PREFIX}events_plugin_ingestion_historical{settings.SUFFIX}",
)
KAFKA_PERSON = f"{settings.KAFKA_PREFIX}clickhouse_person{settings.SUFFIX}"
KAFKA_PERSON_UNIQUE_ID = f"{settings.KAFKA_PREFIX}clickhouse_person_unique_id{settings.SUFFIX}"  # DEPRECATED_DO_NOT_USE
KAFKA_PERSON_DISTINCT_ID = f"{settings.KAFKA_PREFIX}clickhouse_person_distinct_id{settings.SUFFIX}"
KAFKA_PERFORMANCE_EVENTS = f"{settings.KAFKA_PREFIX}clickhouse_performance_events{settings.SUFFIX}"
KAFKA_PLUGIN_LOG_ENTRIES = f"{settings.KAFKA_PREFIX}plugin_log_entries{settings.SUFFIX}"
KAFKA_DEAD_LETTER_QUEUE = f"{settings.KAFKA_PREFIX}events_dead_letter_queue{settings.SUFFIX}"
KAFKA_GROUPS = f"{settings.KAFKA_PREFIX}clickhouse_groups{settings.SUFFIX}"
KAFKA_INGESTION_WARNINGS = f"{settings.KAFKA_PREFIX}clickhouse_ingestion_warnings{settings.SUFFIX}"
KAFKA_APP_METRICS = f"{settings.KAFKA_PREFIX}clickhouse_app_metrics{settings.SUFFIX}"
KAFKA_APP_METRICS2 = f"{settings.KAFKA_PREFIX}clickhouse_app_metrics2{settings.SUFFIX}"
KAFKA_METRICS_TIME_TO_SEE_DATA = f"{settings.KAFKA_PREFIX}clickhouse_metrics_time_to_see_data{settings.SUFFIX}"
KAFKA_PERSON_OVERRIDE = f"{settings.KAFKA_PREFIX}clickhouse_person_override{settings.SUFFIX}"
KAFKA_LOG_ENTRIES = f"{settings.KAFKA_PREFIX}log_entries{settings.SUFFIX}"
KAFKA_LOG_ENTRIES_V2_TEST = f"{settings.KAFKA_PREFIX}log_entries_v2_test{settings.SUFFIX}"

KAFKA_CLICKHOUSE_HEATMAP_EVENTS = f"{settings.KAFKA_PREFIX}clickhouse_heatmap_events{settings.SUFFIX}"

# from capture to recordings consumer
KAFKA_SESSION_RECORDING_EVENTS = f"{settings.KAFKA_PREFIX}session_recording_events{settings.SUFFIX}"
# from capture to recordings blob ingestion consumer
KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS = (
    f"{settings.KAFKA_PREFIX}session_recording_snapshot_item_events{settings.SUFFIX}"
)
KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW = (
    f"{settings.KAFKA_PREFIX}session_recording_snapshot_item_overflow{settings.SUFFIX}"
)

# from recordings consumer to clickhouse
KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS = f"{settings.KAFKA_PREFIX}clickhouse_session_replay_events{settings.SUFFIX}"
KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS = (
    f"{settings.KAFKA_PREFIX}clickhouse_session_recording_events{settings.SUFFIX}"
)

KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT = (
    f"{settings.KAFKA_PREFIX}clickhouse_error_tracking_issue_fingerprint{settings.SUFFIX}"
)
KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_EMBEDDINGS = (
    f"{settings.KAFKA_PREFIX}clickhouse_error_tracking_issue_fingerprint_embeddings{settings.SUFFIX}"
)

KAFKA_CDP_INTERNAL_EVENTS = f"{settings.KAFKA_PREFIX}cdp_internal_events{settings.SUFFIX}"
