// Keep this in sync with posthog/kafka_client/topics.py

import { isTestEnv } from '../utils/env-utils'

export const suffix = isTestEnv() ? '_test' : ''
export const prefix = process.env.KAFKA_PREFIX || ''

export const KAFKA_EVENTS_JSON = `${prefix}clickhouse_events_json${suffix}`
export const KAFKA_PERSON = `${prefix}clickhouse_person${suffix}`
export const KAFKA_PERSON_UNIQUE_ID = `${prefix}clickhouse_person_unique_id${suffix}`
export const KAFKA_PERSON_DISTINCT_ID = `${prefix}clickhouse_person_distinct_id${suffix}`

export const KAFKA_EVENTS_PLUGIN_INGESTION = `${prefix}events_plugin_ingestion${suffix}`
export const KAFKA_EVENTS_PLUGIN_INGESTION_DLQ = `${prefix}events_plugin_ingestion_dlq${suffix}`
export const KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW = `${prefix}events_plugin_ingestion_overflow${suffix}`
export const KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL = `${prefix}events_plugin_ingestion_historical${suffix}`
export const KAFKA_PLUGIN_LOG_ENTRIES = `${prefix}plugin_log_entries${suffix}`
export const KAFKA_EVENTS_DEAD_LETTER_QUEUE = `${prefix}events_dead_letter_queue${suffix}`
export const KAFKA_GROUPS = `${prefix}clickhouse_groups${suffix}`
export const KAFKA_BUFFER = `${prefix}conversion_events_buffer${suffix}`
export const KAFKA_INGESTION_WARNINGS = `${prefix}clickhouse_ingestion_warnings${suffix}`
export const KAFKA_APP_METRICS = `${prefix}clickhouse_app_metrics${suffix}`
export const KAFKA_APP_METRICS_2 = `${prefix}clickhouse_app_metrics2${suffix}`
export const KAFKA_JOBS = `${prefix}jobs${suffix}`
export const KAFKA_JOBS_DLQ = `${prefix}jobs_dlq${suffix}`
export const KAFKA_SCHEDULED_TASKS = `${prefix}scheduled_tasks${suffix}`
export const KAFKA_SCHEDULED_TASKS_DLQ = `${prefix}scheduled_tasks_dlq${suffix}`
export const KAFKA_METRICS_TIME_TO_SEE_DATA = `${prefix}clickhouse_metrics_time_to_see_data${suffix}`

// read session recording snapshot items
export const KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS = `${prefix}session_recording_snapshot_item_events${suffix}`
export const KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW = `${prefix}session_recording_snapshot_item_overflow${suffix}`

// write session recording and replay events to ClickHouse
export const KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS = `${prefix}clickhouse_session_recording_events${suffix}`
export const KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS = `${prefix}clickhouse_session_replay_events${suffix}`
// write performance events to ClickHouse
export const KAFKA_PERFORMANCE_EVENTS = `${prefix}clickhouse_performance_events${suffix}`
// write heatmap events to ClickHouse
export const KAFKA_CLICKHOUSE_HEATMAP_EVENTS = `${prefix}clickhouse_heatmap_events${suffix}`

// log entries for ingestion into clickhouse
export const KAFKA_LOG_ENTRIES = `${prefix}log_entries${suffix}`

// CDP topics
export const KAFKA_CDP_FUNCTION_CALLBACKS = `${prefix}cdp_function_callbacks${suffix}`
export const KAFKA_CDP_FUNCTION_OVERFLOW = `${prefix}cdp_function_overflow${suffix}`
