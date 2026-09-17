// Keep this in sync with posthog/kafka_client/topics.py
import { isTestEnv } from '../utils/env-utils'

export const suffix = isTestEnv() ? '_test' : ''
export const prefix = process.env.KAFKA_PREFIX || ''

export const KAFKA_EVENTS_JSON = `${prefix}clickhouse_events_json${suffix}`
export const KAFKA_EVENTS_RECENT_JSON = `${prefix}kafka_events_recent_json${suffix}`
export const KAFKA_PERSON = `${prefix}clickhouse_person${suffix}`
export const KAFKA_PERSON_OVERRIDES = `${prefix}clickhouse_person_overrides${suffix}`
export const KAFKA_PERSON_UNIQUE_ID = `${prefix}clickhouse_person_unique_id${suffix}`
export const KAFKA_PERSON_DISTINCT_ID = `${prefix}clickhouse_person_distinct_id${suffix}`
export const KAFKA_PERSON_DISTINCT_ID_OVERRIDES = `${prefix}clickhouse_person_distinct_id_overrides${suffix}`
export const KAFKA_PERSON_DISTINCT_ID2 = `${prefix}clickhouse_person_distinct_id2${suffix}`

export const KAFKA_EVENTS_PLUGIN_INGESTION = `${prefix}events_plugin_ingestion${suffix}`
export const KAFKA_EVENTS_PLUGIN_INGESTION_DLQ = `${prefix}events_plugin_ingestion_dlq${suffix}`
export const KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW = `${prefix}events_plugin_ingestion_overflow${suffix}`
export const KAFKA_EVENTS_PLUGIN_INGESTION_AI = `${prefix}events_plugin_ingestion_ai${suffix}`
export const KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC = `${prefix}events_plugin_ingestion_async${suffix}`
export const KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL = `${prefix}events_plugin_ingestion_historical${suffix}`
export const KAFKA_PLUGIN_LOG_ENTRIES = `${prefix}plugin_log_entries${suffix}`
export const KAFKA_EVENTS_DEAD_LETTER_QUEUE = `${prefix}events_dead_letter_queue${suffix}`
export const KAFKA_GROUPS = `${prefix}clickhouse_groups${suffix}`
export const KAFKA_BUFFER = `${prefix}conversion_events_buffer${suffix}`
export const KAFKA_INGESTION_WARNINGS = `${prefix}clickhouse_ingestion_warnings${suffix}`
export const KAFKA_APP_METRICS_2 = `${prefix}clickhouse_app_metrics2${suffix}`
export const KAFKA_METRICS_TIME_TO_SEE_DATA = `${prefix}clickhouse_metrics_time_to_see_data${suffix}`

// read session recording snapshot items
export const KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS = `${prefix}session_recording_snapshot_item_events${suffix}`
export const KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW = `${prefix}session_recording_snapshot_item_overflow${suffix}`
export const KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_DLQ = `${prefix}session_recording_snapshot_item_dlq${suffix}`

// write session recording and replay events to ClickHouse
export const KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS = `${prefix}clickhouse_session_recording_events${suffix}`
export const KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS = `${prefix}clickhouse_session_replay_events${suffix}`
export const KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES = `${prefix}clickhouse_session_replay_features${suffix}`

// anonymized block metadata mirrored to the ML account (consumed by the Parquet sink, not ClickHouse)
export const KAFKA_SESSION_REPLAY_ML_BLOCK_METADATA = `${prefix}session_replay_ml_block_metadata${suffix}`

// raw inlined replay images: ml-mirror producer -> image-scrub worker
export const KAFKA_SESSION_REPLAY_IMAGE_SCRUB = `${prefix}session_replay_image_scrub${suffix}`

// remote image URLs: ml-mirror producer -> image-fetch worker. The Kafka key is the registrable
// domain, not the host. All URLs of one operator therefore go to one partition, and one pod owns
// the request rate of that operator. A CDN that shards over img1..img8.cdn.example.com keys to
// example.com, so it gets one budget rather than eight. A record holds an original, unscrubbed
// URL, so this topic is as sensitive as the raw replay topic.
export const KAFKA_SESSION_REPLAY_IMAGE_FETCH = `${prefix}session_replay_image_fetch${suffix}`
// Kafka has no delayed delivery, so a retry waits in a topic whose period is fixed. The period
// belongs to the topic rather than to the record, so the records leave in the order they become
// ready and an hour-long wait never sits in front of a one minute wait.
export const KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1M = `${prefix}ai_research_session_replay_image_fetch_retry_1m${suffix}`
export const KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_10M = `${prefix}ai_research_session_replay_image_fetch_retry_10m${suffix}`
export const KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1H = `${prefix}ai_research_session_replay_image_fetch_retry_1h${suffix}`

// images the scrub sidecar cannot process, parked so they stop holding the head of their partition.
// The original bytes are kept: unscrubbed content must never reach the ML bucket, but it must not be
// thrown away either, so it waits here for the sidecar bug behind it to be fixed and replayed.
export const KAFKA_SESSION_REPLAY_IMAGE_SCRUB_DLQ = `${prefix}session_replay_image_scrub_dlq${suffix}`

// write performance events to ClickHouse
export const KAFKA_PERFORMANCE_EVENTS = `${prefix}clickhouse_performance_events${suffix}`
// write heatmap events to ClickHouse
export const KAFKA_CLICKHOUSE_HEATMAP_EVENTS = `${prefix}clickhouse_heatmap_events${suffix}`
// write AI events to ClickHouse
export const KAFKA_CLICKHOUSE_AI_EVENTS_JSON = `${prefix}clickhouse_ai_events_json${suffix}`
// write flag evaluations ($feature_flag_called telemetry) to ClickHouse
export const KAFKA_CLICKHOUSE_FLAG_EVALUATIONS = `${prefix}clickhouse_flag_evaluations${suffix}`

// log entries for ingestion into ClickHouse
export const KAFKA_LOG_ENTRIES = `${prefix}log_entries${suffix}`

// per-invocation result rows for hog functions and hog flows
export const KAFKA_HOG_INVOCATION_RESULTS = `${prefix}clickhouse_hog_invocation_results${suffix}`

// metadata rows for sent message assets (rendered emails stored in object storage)
export const KAFKA_MESSAGE_ASSETS = `${prefix}clickhouse_message_assets${suffix}`

// CDP topics
export const KAFKA_CDP_FUNCTION_OVERFLOW = `${prefix}cdp_function_overflow${suffix}`
export const KAFKA_CDP_INTERNAL_EVENTS = `${prefix}cdp_internal_events${suffix}`
export const KAFKA_CDP_CLICKHOUSE_BEHAVIORAL_COHORTS_MATCHES = `${prefix}clickhouse_behavioral_cohorts_matches${suffix}`
export const KAFKA_COHORT_MEMBERSHIP_CHANGED = `${prefix}cohort_membership_changed${suffix}`
// One completion marker per processor partition, certifying that a reconcile run replayed a
// cohort's full membership. Produced by the cohort-stream-processor (Rust).
export const KAFKA_COHORT_RECONCILE_MARKERS = `${prefix}cohort_reconcile_markers${suffix}`
// Cross-partition merge protocol trigger consumed by the cohort-stream-processor (Rust).
export const KAFKA_PERSON_MERGE_EVENTS = `${prefix}person_merge_events${suffix}`

// Error tracking topics
export const KAFKA_ERROR_TRACKING_INGESTION = `${prefix}ingestion-errortracking-main${suffix}` // Partition count varies by env
export const KAFKA_ERROR_TRACKING_INGESTION_DLQ = `${prefix}ingestion-errortracking-main-dlq${suffix}`
export const KAFKA_ERROR_TRACKING_INGESTION_OVERFLOW = `${prefix}ingestion-errortracking-overflow${suffix}` // Partition count varies by env
export const KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT = `${prefix}clickhouse_error_tracking_issue_fingerprint${suffix}`
export const KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES = `${prefix}clickhouse_error_tracking_issue_fingerprint_overrides${suffix}`

// Warehouse source webhook ingestion
export const KAFKA_WAREHOUSE_SOURCE_WEBHOOKS = `${prefix}data_warehouse_source_webhooks${suffix}`

// Logs ingestion topics
export const KAFKA_LOGS_INGESTION = `${prefix}logs_ingestion${suffix}`
export const KAFKA_LOGS_INGESTION_DLQ = `${prefix}logs_ingestion_dlq${suffix}`
export const KAFKA_LOGS_INGESTION_OVERFLOW = `${prefix}logs_ingestion_overflow${suffix}`
export const KAFKA_LOGS_CLICKHOUSE = `${prefix}clickhouse_logs${suffix}`

// Traces ingestion topics
export const KAFKA_TRACES_INGESTION = `${prefix}ingestion-traces${suffix}`
export const KAFKA_TRACES_INGESTION_DLQ = `${prefix}ingestion-traces-dlq${suffix}`
export const KAFKA_TRACES_INGESTION_OVERFLOW = `${prefix}ingestion-traces-overflow${suffix}`
export const KAFKA_TRACES_CLICKHOUSE = `${prefix}clickhouse_traces${suffix}`
// Metrics ingestion topics
export const KAFKA_METRICS_INGESTION = `${prefix}metrics_ingestion${suffix}`
export const KAFKA_METRICS_INGESTION_DLQ = `${prefix}metrics_ingestion_dlq${suffix}`
export const KAFKA_METRICS_INGESTION_OVERFLOW = `${prefix}metrics_ingestion_overflow${suffix}`
export const KAFKA_METRICS_CLICKHOUSE = `${prefix}clickhouse_metrics${suffix}`

// TopHog metrics
export const KAFKA_CLICKHOUSE_TOPHOG = `${prefix}clickhouse_tophog${suffix}`
