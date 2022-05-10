// Keep this in sync with ee/kafka_client/topics.py

import { determineNodeEnv, NodeEnv } from '../utils/env-utils'

const isTestEnv = determineNodeEnv() === NodeEnv.Test
const suffix = isTestEnv ? '_test' : ''

export const KAFKA_EVENTS = `clickhouse_events_proto${suffix}`
export const KAFKA_EVENTS_JSON = `clickhouse_events_json${suffix}`
export const KAFKA_PERSON = `clickhouse_person${suffix}`
export const KAFKA_PERSON_UNIQUE_ID = `clickhouse_person_unique_id${suffix}`
export const KAFKA_PERSON_DISTINCT_ID = `clickhouse_person_distinct_id${suffix}`
export const KAFKA_SESSION_RECORDING_EVENTS = `clickhouse_session_recording_events${suffix}`
export const KAFKA_EVENTS_PLUGIN_INGESTION = `events_plugin_ingestion${suffix}`
export const KAFKA_PLUGIN_LOG_ENTRIES = `plugin_log_entries${suffix}`
export const KAFKA_EVENTS_DEAD_LETTER_QUEUE = `events_dead_letter_queue${suffix}`
export const KAFKA_GROUPS = `clickhouse_groups${suffix}`
export const KAFKA_BUFFER = `conversion_events_buffer${suffix}`
export const KAFKA_HEALTHCHECK = `healthcheck${suffix}`
