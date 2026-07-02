/**
 * Recording API Types
 *
 * Re-exports shared encryption types from session-replay/types.ts and adds
 * Recording API-specific types.
 */
import { CommonConfig } from '~/common/config'
import {
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
    KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES,
} from '~/common/config/kafka-topics'
import { SessionRecordingApiConfig, SessionRecordingConfig } from '~/ingestion/pipelines/sessionreplay/config'
import {
    INGESTION_SESSIONREPLAY_PRODUCER,
    type IngestionSessionreplayProducer,
} from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'

/**
 * Recording API's outputs are ClickHouse-bound deletion tombstones on the warpstream-replay
 * cluster, produced through the INGESTION_SESSIONREPLAY slot.
 */
export type RecordingApiProducerName = IngestionSessionreplayProducer

// Re-export all shared encryption types so existing recording-api imports still work
export {
    SessionKeyDeletedError,
    type DecryptResult,
    type DeleteKeyResult,
    type EncryptResult,
    type KeyStore,
    type RecordingDecryptor,
    type RecordingEncryptor,
    type SerializedSessionKey,
    type SessionKey,
    type SessionState,
} from '~/ingestion/pipelines/sessionreplay/shared/types'

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
        RECORDING_API_OUTPUT_REPLAY_EVENTS_PRODUCER: INGESTION_SESSIONREPLAY_PRODUCER,
        RECORDING_API_OUTPUT_SESSION_FEATURES_TOPIC: KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES,
        RECORDING_API_OUTPUT_SESSION_FEATURES_PRODUCER: INGESTION_SESSIONREPLAY_PRODUCER,
    }
}

export interface RecordingBlock {
    key: string
    start_byte: number
    end_byte: number
    start_timestamp: string
    end_timestamp: string
}
