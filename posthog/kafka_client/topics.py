# Keep this in sync with plugin-server/src/config/kafka-topics.ts

from posthog.settings.data_stores import KAFKA_PREFIX, SUFFIX
from posthog.settings.utils import get_from_env

KAFKA_EVENTS_JSON = f"{KAFKA_PREFIX}clickhouse_events_json{SUFFIX}"
KAFKA_EXCEPTIONS_INGESTION = f"{KAFKA_PREFIX}exceptions_ingestion{SUFFIX}"
KAFKA_EVENTS_PLUGIN_INGESTION = get_from_env(
    "KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC", f"{KAFKA_PREFIX}events_plugin_ingestion{SUFFIX}"
)
KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW = get_from_env(
    "KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW_TOPIC", f"{KAFKA_PREFIX}events_plugin_ingestion_overflow{SUFFIX}"
)
KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL = get_from_env(
    "KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL_TOPIC", f"{KAFKA_PREFIX}events_plugin_ingestion_historical{SUFFIX}"
)
KAFKA_PERSON = f"{KAFKA_PREFIX}clickhouse_person{SUFFIX}"
KAFKA_PERSON_UNIQUE_ID = f"{KAFKA_PREFIX}clickhouse_person_unique_id{SUFFIX}"  # DEPRECATED_DO_NOT_USE
KAFKA_PERSON_DISTINCT_ID = f"{KAFKA_PREFIX}clickhouse_person_distinct_id{SUFFIX}"
KAFKA_PERFORMANCE_EVENTS = f"{KAFKA_PREFIX}clickhouse_performance_events{SUFFIX}"
KAFKA_PLUGIN_LOG_ENTRIES = f"{KAFKA_PREFIX}plugin_log_entries{SUFFIX}"
KAFKA_DEAD_LETTER_QUEUE = f"{KAFKA_PREFIX}events_dead_letter_queue{SUFFIX}"
KAFKA_GROUPS = f"{KAFKA_PREFIX}clickhouse_groups{SUFFIX}"
KAFKA_INGESTION_WARNINGS = f"{KAFKA_PREFIX}clickhouse_ingestion_warnings{SUFFIX}"
KAFKA_APP_METRICS = f"{KAFKA_PREFIX}clickhouse_app_metrics{SUFFIX}"
KAFKA_APP_METRICS2 = f"{KAFKA_PREFIX}clickhouse_app_metrics2{SUFFIX}"
KAFKA_METRICS_TIME_TO_SEE_DATA = f"{KAFKA_PREFIX}clickhouse_metrics_time_to_see_data{SUFFIX}"
KAFKA_PERSON_OVERRIDE = f"{KAFKA_PREFIX}clickhouse_person_override{SUFFIX}"
KAFKA_LOG_ENTRIES = f"{KAFKA_PREFIX}log_entries{SUFFIX}"
KAFKA_LOG_ENTRIES_V2_TEST = f"{KAFKA_PREFIX}log_entries_v2_test{SUFFIX}"

KAFKA_CLICKHOUSE_HEATMAP_EVENTS = f"{KAFKA_PREFIX}clickhouse_heatmap_events{SUFFIX}"

# from capture to recordings consumer
KAFKA_SESSION_RECORDING_EVENTS = f"{KAFKA_PREFIX}session_recording_events{SUFFIX}"
# from capture to recordings blob ingestion consumer
KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS = f"{KAFKA_PREFIX}session_recording_snapshot_item_events{SUFFIX}"
KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW = f"{KAFKA_PREFIX}session_recording_snapshot_item_overflow{SUFFIX}"

# from recordings consumer to clickhouse
KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS = f"{KAFKA_PREFIX}clickhouse_session_replay_events{SUFFIX}"
KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS = f"{KAFKA_PREFIX}clickhouse_session_recording_events{SUFFIX}"
KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS_V2_TEST = f"{KAFKA_PREFIX}clickhouse_session_replay_events_v2_test{SUFFIX}"

KAFKA_EXCEPTION_SYMBOLIFICATION_EVENTS = f"{KAFKA_PREFIX}exception_symbolification_events{SUFFIX}"
KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT = f"{KAFKA_PREFIX}clickhouse_error_tracking_issue_fingerprint{SUFFIX}"

KAFKA_CDP_INTERNAL_EVENTS = f"{KAFKA_PREFIX}cdp_internal_events{SUFFIX}"
