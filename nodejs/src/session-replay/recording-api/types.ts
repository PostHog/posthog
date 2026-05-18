/**
 * Recording API Types
 *
 * Re-exports shared encryption types from session-replay/types.ts and adds
 * Recording API-specific types.
 */
import { CommonConfig } from '../../common/config'
import {
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
    KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES,
} from '../../config/kafka-topics'
import { DEFAULT_PRODUCER, type DefaultProducer, type WarpstreamProducer } from '../../ingestion/common/outputs'
import { SessionRecordingApiConfig, SessionRecordingConfig } from '../../session-recording/config'

/**
 * Recording API only needs DEFAULT + WARPSTREAM producers — its outputs are
 * ClickHouse-bound deletion tombstones, so the ingestion-internal cluster
 * (INGESTION) is not a relevant target here.
 */
export type RecordingApiProducerName = DefaultProducer | WarpstreamProducer

// Re-export all shared encryption types so existing recording-api imports still work
export {
    DecryptResult,
    DeleteKeyResult,
    EncryptResult,
    KeyStore,
    RecordingDecryptor,
    RecordingEncryptor,
    SerializedSessionKey,
    SessionKey,
    SessionKeyDeletedError,
    SessionState,
} from '../shared/types'

/**
 * Configuration for the Recording API.
 * Postgres is passed as an explicit constructor param, not included here.
 */
export type RecordingApiConfig = Pick<
    CommonConfig,
    'KAFKA_CLIENT_RACK' | 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE'
> &
    Pick<
        SessionRecordingApiConfig,
        | 'SESSION_RECORDING_API_REDIS_HOST'
        | 'SESSION_RECORDING_API_REDIS_PORT'
        | 'SESSION_RECORDING_KMS_ENDPOINT'
        | 'SESSION_RECORDING_DYNAMODB_ENDPOINT'
        | 'CLICKHOUSE_HOST'
        | 'CLICKHOUSE_DATABASE'
        | 'CLICKHOUSE_USER'
        | 'CLICKHOUSE_PASSWORD'
        | 'CLICKHOUSE_SECURE'
    > &
    Pick<
        SessionRecordingConfig,
        | 'SESSION_RECORDING_V2_S3_REGION'
        | 'SESSION_RECORDING_V2_S3_ENDPOINT'
        | 'SESSION_RECORDING_V2_S3_ACCESS_KEY_ID'
        | 'SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY'
        | 'SESSION_RECORDING_V2_S3_BUCKET'
        | 'SESSION_RECORDING_V2_S3_PREFIX'
    >

/**
 * Recording API outputs — topic and producer routing per output. All keys
 * follow the `RECORDING_API_OUTPUT_*` convention. Topic values default to
 * the same Kafka topics the session-replay ingestion consumer writes to,
 * since recording-api emits deletion tombstones into the same streams.
 */
export type RecordingApiOutputsConfig = {
    RECORDING_API_OUTPUT_REPLAY_EVENTS_TOPIC: string
    RECORDING_API_OUTPUT_REPLAY_EVENTS_PRODUCER: RecordingApiProducerName

    RECORDING_API_OUTPUT_SESSION_FEATURES_TOPIC: string
    RECORDING_API_OUTPUT_SESSION_FEATURES_PRODUCER: RecordingApiProducerName
}

export function getDefaultRecordingApiOutputsConfig(): RecordingApiOutputsConfig {
    return {
        RECORDING_API_OUTPUT_REPLAY_EVENTS_TOPIC: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
        RECORDING_API_OUTPUT_REPLAY_EVENTS_PRODUCER: DEFAULT_PRODUCER,
        RECORDING_API_OUTPUT_SESSION_FEATURES_TOPIC: KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES,
        RECORDING_API_OUTPUT_SESSION_FEATURES_PRODUCER: DEFAULT_PRODUCER,
    }
}

export interface RecordingBlock {
    key: string
    start_byte: number
    end_byte: number
    start_timestamp: string
    end_timestamp: string
}
