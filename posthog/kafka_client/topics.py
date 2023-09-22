# Keep this in sync with plugin-server/src/config/kafka-topics.ts

from posthog.settings.data_stores import KAFKA_PREFIX, SUFFIX

KAFKA_EVENTS_JSON = f"{KAFKA_PREFIX}clickhouse_events_json{SUFFIX}"
KAFKA_EVENTS_PLUGIN_INGESTION = f"{KAFKA_PREFIX}events_plugin_ingestion{SUFFIX}"
KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW = f"{KAFKA_PREFIX}events_plugin_ingestion_overflow{SUFFIX}"
KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL = f"{KAFKA_PREFIX}events_plugin_ingestion_historical{SUFFIX}"
KAFKA_PERSON = f"{KAFKA_PREFIX}clickhouse_person{SUFFIX}"
KAFKA_PERSON_UNIQUE_ID = f"{KAFKA_PREFIX}clickhouse_person_unique_id{SUFFIX}"  # DEPRECATED_DO_NOT_USE
KAFKA_PERSON_DISTINCT_ID = f"{KAFKA_PREFIX}clickhouse_person_distinct_id{SUFFIX}"
KAFKA_PERSON_OVERRIDES = f"{KAFKA_PREFIX}clickhouse_person_override{SUFFIX}"
KAFKA_PERFORMANCE_EVENTS = f"{KAFKA_PREFIX}clickhouse_performance_events{SUFFIX}"
KAFKA_PLUGIN_LOG_ENTRIES = f"{KAFKA_PREFIX}plugin_log_entries{SUFFIX}"
KAFKA_DEAD_LETTER_QUEUE = f"{KAFKA_PREFIX}events_dead_letter_queue{SUFFIX}"
KAFKA_GROUPS = f"{KAFKA_PREFIX}clickhouse_groups{SUFFIX}"
KAFKA_INGESTION_WARNINGS = f"{KAFKA_PREFIX}clickhouse_ingestion_warnings{SUFFIX}"
KAFKA_APP_METRICS = f"{KAFKA_PREFIX}clickhouse_app_metrics{SUFFIX}"
KAFKA_METRICS_TIME_TO_SEE_DATA = f"{KAFKA_PREFIX}clickhouse_metrics_time_to_see_data{SUFFIX}"
KAFKA_PERSON_OVERRIDE = f"{KAFKA_PREFIX}clickhouse_person_override{SUFFIX}"
KAFKA_LOG_ENTRIES = f"{KAFKA_PREFIX}log_entries{SUFFIX}"

# from capture to recordings consumer
KAFKA_SESSION_RECORDING_EVENTS = f"{KAFKA_PREFIX}session_recording_events{SUFFIX}"
# from capture to recordings blob ingestion consumer
KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS = f"{KAFKA_PREFIX}session_recording_snapshot_item_events{SUFFIX}"
# from recordings consumer to clickhouse
KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS = f"{KAFKA_PREFIX}clickhouse_session_replay_events{SUFFIX}"
KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS = f"{KAFKA_PREFIX}clickhouse_session_recording_events{SUFFIX}"
