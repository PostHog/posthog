# Keep this in sync with plugin-server/src/config/kafka-topics.ts

import os

from posthog.settings import TEST

suffix = "_test" if TEST else ""
prefix = os.getenv("KAFKA_PREFIX", "")

KAFKA_EVENTS_PLUGIN_INGESTION: str = f"{prefix}events_plugin_ingestion{suffix}"  # can be overridden in settings.py
KAFKA_EVENTS = f"{prefix}clickhouse_events_proto{suffix}"
KAFKA_EVENTS_JSON = f"{prefix}clickhouse_events_json{suffix}"
KAFKA_PERSON = f"{prefix}clickhouse_person{suffix}"
KAFKA_PERSON_UNIQUE_ID = f"{prefix}clickhouse_person_unique_id{suffix}"
KAFKA_PERSON_DISTINCT_ID = f"{prefix}clickhouse_person_distinct_id{suffix}"
KAFKA_SESSION_RECORDING_EVENTS = f"{prefix}clickhouse_session_recording_events{suffix}"
KAFKA_PLUGIN_LOG_ENTRIES = f"{prefix}plugin_log_entries{suffix}"
KAFKA_DEAD_LETTER_QUEUE = f"{prefix}events_dead_letter_queue{suffix}"
KAFKA_GROUPS = f"{prefix}clickhouse_groups{suffix}"
