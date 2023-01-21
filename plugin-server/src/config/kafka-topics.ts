// Keep this in sync with posthog/kafka_client/topics.py

import { isTestEnv } from '../utils/env-utils'

const suffix = isTestEnv() ? '_test' : ''
export const prefix = process.env.KAFKA_PREFIX || ''

export const KAFKA_EVENTS = `${prefix}clickhouse_events_proto${suffix}`
export const KAFKA_EVENTS_JSON = `${prefix}clickhouse_events_json${suffix}`
export const KAFKA_PERSON = `${prefix}clickhouse_person${suffix}`
export const KAFKA_PERSON_UNIQUE_ID = `${prefix}clickhouse_person_unique_id${suffix}`
export const KAFKA_PERSON_DISTINCT_ID = `${prefix}clickhouse_person_distinct_id${suffix}`
export const KAFKA_SESSION_RECORDING_EVENTS = `${prefix}clickhouse_session_recording_events${suffix}`
export const KAFKA_EVENTS_PLUGIN_INGESTION = `${prefix}events_plugin_ingestion${suffix}`
export const KAFKA_PLUGIN_LOG_ENTRIES = `${prefix}plugin_log_entries${suffix}`
export const KAFKA_EVENTS_DEAD_LETTER_QUEUE = `${prefix}events_dead_letter_queue${suffix}`
export const KAFKA_GROUPS = `${prefix}clickhouse_groups${suffix}`
export const KAFKA_BUFFER = `${prefix}conversion_events_buffer${suffix}`
export const KAFKA_HEALTHCHECK = `${prefix}healthcheck${suffix}`
