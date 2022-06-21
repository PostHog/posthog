# Keep this in sync with plugin-server/src/config/kafka-topics.ts

from posthog.settings import TEST
from posthog.settings.data_stores import KAFKA_PREFIX

suffix = "_test" if TEST else ""

KAFKA_EVENTS_PLUGIN_INGESTION: str = (
    f"{KAFKA_PREFIX}events_plugin_ingestion{suffix}"  # can be overridden in settings.py
)
KAFKA_EVENTS = f"{KAFKA_PREFIX}clickhouse_events_proto{suffix}"
KAFKA_EVENTS_JSON = f"{KAFKA_PREFIX}clickhouse_events_json{suffix}"
KAFKA_PERSON = f"{KAFKA_PREFIX}clickhouse_person{suffix}"
KAFKA_PERSON_UNIQUE_ID = f"{KAFKA_PREFIX}clickhouse_person_unique_id{suffix}"
KAFKA_PERSON_DISTINCT_ID = f"{KAFKA_PREFIX}clickhouse_person_distinct_id{suffix}"
KAFKA_SESSION_RECORDING_EVENTS = f"{KAFKA_PREFIX}clickhouse_session_recording_events{suffix}"
KAFKA_SESSION_RECORDINGS = f"{KAFKA_PREFIX}clickhouse_session_recordings{suffix}"
KAFKA_PLUGIN_LOG_ENTRIES = f"{KAFKA_PREFIX}plugin_log_entries{suffix}"
KAFKA_DEAD_LETTER_QUEUE = f"{KAFKA_PREFIX}events_dead_letter_queue{suffix}"
KAFKA_GROUPS = f"{KAFKA_PREFIX}clickhouse_groups{suffix}"
