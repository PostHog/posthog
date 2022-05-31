# Keep this in sync with plugin-server/src/config/kafka-topics.ts

from ee.kafka_client.topic_definitions import TopicDefinition
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
KAFKA_PLUGIN_LOG_ENTRIES = f"{KAFKA_PREFIX}plugin_log_entries{suffix}"
KAFKA_DEAD_LETTER_QUEUE = f"{KAFKA_PREFIX}events_dead_letter_queue{suffix}"
KAFKA_GROUPS = f"{KAFKA_PREFIX}clickhouse_groups{suffix}"
KAFKA_EVENTS_PLUGIN_INGESTION = f"{KAFKA_PREFIX}events_plugin_ingestion{suffix}"
KAFKA_BUFFER = f"{KAFKA_PREFIX}conversion_events_buffer{suffix}"
KAFKA_HEALTHCHECK = f"{KAFKA_PREFIX}healthcheck{suffix}"


KAFKA_TOPIC_DEFINITIONS = [
    TopicDefinition(KAFKA_EVENTS_PLUGIN_INGESTION, 128),
    TopicDefinition(KAFKA_EVENTS, 128),
    TopicDefinition(KAFKA_EVENTS_JSON, 256),
    TopicDefinition(KAFKA_PERSON, 128),
    TopicDefinition(KAFKA_PERSON_UNIQUE_ID, 128),
    TopicDefinition(KAFKA_PERSON_DISTINCT_ID, 128),
    TopicDefinition(KAFKA_SESSION_RECORDING_EVENTS, 128),
    TopicDefinition(KAFKA_PLUGIN_LOG_ENTRIES, 128),
    TopicDefinition(KAFKA_DEAD_LETTER_QUEUE, 128),
    TopicDefinition(KAFKA_GROUPS, 128),
    TopicDefinition(KAFKA_EVENTS_PLUGIN_INGESTION, 128),
    TopicDefinition(KAFKA_BUFFER, 128),
    TopicDefinition(KAFKA_HEALTHCHECK, 64),
]
