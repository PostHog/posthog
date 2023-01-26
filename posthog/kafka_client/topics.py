# Keep this in sync with plugin-server/src/config/kafka-topics.ts

from posthog.settings.data_stores import KAFKA_PREFIX, SUFFIX

KAFKA_EVENTS_JSON = f"{KAFKA_PREFIX}clickhouse_events_json{SUFFIX}"
KAFKA_PERSON = f"{KAFKA_PREFIX}clickhouse_person{SUFFIX}"
KAFKA_PERSON_UNIQUE_ID = f"{KAFKA_PREFIX}clickhouse_person_unique_id{SUFFIX}"  # DEPRECATED_DO_NOT_USE
KAFKA_PERSON_DISTINCT_ID = f"{KAFKA_PREFIX}clickhouse_person_distinct_id{SUFFIX}"
KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS = f"{KAFKA_PREFIX}clickhouse_session_recording_events{SUFFIX}"
KAFKA_PERFORMANCE_EVENTS = f"{KAFKA_PREFIX}clickhouse_performance_events{SUFFIX}"
KAFKA_PLUGIN_LOG_ENTRIES = f"{KAFKA_PREFIX}plugin_log_entries{SUFFIX}"
KAFKA_DEAD_LETTER_QUEUE = f"{KAFKA_PREFIX}events_dead_letter_queue{SUFFIX}"
KAFKA_GROUPS = f"{KAFKA_PREFIX}clickhouse_groups{SUFFIX}"
KAFKA_INGESTION_WARNINGS = f"{KAFKA_PREFIX}clickhouse_ingestion_warnings{SUFFIX}"
KAFKA_APP_METRICS = f"{KAFKA_PREFIX}clickhouse_app_metrics{SUFFIX}"
KAFKA_METRICS_TIME_TO_SEE_DATA = f"{KAFKA_PREFIX}clickhouse_metrics_time_to_see_data{SUFFIX}"
KAFKA_SESSION_RECORDING_EVENTS = f"{KAFKA_PREFIX}session_recording_events{SUFFIX}"
KAFKA_PERSON_OVERRIDE = f"{KAFKA_PREFIX}clickhouse_person_override{SUFFIX}"
