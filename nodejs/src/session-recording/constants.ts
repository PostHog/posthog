import {
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW,
} from '../config/kafka-topics'

// WARNING: Do not change these - they will essentially reset the consumer
export const KAFKA_CONSUMER_GROUP_ID = 'session-recordings-blob-v2'
export const KAFKA_CONSUMER_GROUP_ID_OVERFLOW = 'session-recordings-blob-v2-overflow'
export const KAFKA_CONSUMER_SESSION_TIMEOUT_MS = 90_000

// Re-export kafka topics constants
export { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS, KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW }

// Re-export shared retention constants so existing recording-ingestion imports still work
export { RetentionPeriodToDaysMap, ValidRetentionPeriods } from '../session-replay/constants'

// Maximum length of a session recording (24 hours)
export const MAX_SESSION_LENGTH_SECONDS = 24 * 60 * 60

// Redis TTL for session tracking keys
// Set to 2x max session length for safety margin (handles edge cases like
// sessions that span across the boundary, delayed messages, etc.)
export const SESSION_TRACKER_REDIS_TTL_SECONDS = 2 * MAX_SESSION_LENGTH_SECONDS

// Redis TTL for session blocklist keys
// Matches session tracker TTL since blocked sessions should persist for same duration
export const SESSION_FILTER_REDIS_TTL_SECONDS = 2 * MAX_SESSION_LENGTH_SECONDS
