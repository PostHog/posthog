import {
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW,
} from '../../../config/kafka-topics'
import { RetentionPeriod } from './types'

// WARNING: Do not change these - they will essentially reset the consumer
export const KAFKA_CONSUMER_GROUP_ID = 'session-recordings-blob-v2'
export const KAFKA_CONSUMER_GROUP_ID_OVERFLOW = 'session-recordings-blob-v2-overflow'
export const KAFKA_CONSUMER_SESSION_TIMEOUT_MS = 90_000

// Re-export kafka topics constants
export { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS, KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW }

export const ValidRetentionPeriods = ['30d', '90d', '1y', '5y'] as const

export const RetentionPeriodToDaysMap: { [key in RetentionPeriod]: number | null } = {
    '30d': 30,
    '90d': 90,
    '1y': 365,
    '5y': 1825,
}
