/**
 * Recording API Types
 *
 * Re-exports shared encryption types from session-replay/types.ts and adds
 * Recording API-specific types.
 */
import { CommonConfig } from '../../common/config'
import { DEFAULT_PRODUCER } from '../../ingestion/common/outputs'
import {
    SessionRecordingApiConfig,
    SessionRecordingConfig,
    SessionReplayProducerName,
} from '../../session-recording/config'

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
        | 'SESSION_RECORDING_V2_REPLAY_EVENTS_KAFKA_TOPIC'
        | 'SESSION_RECORDING_V2_SESSION_FEATURES_KAFKA_TOPIC'
    >

/**
 * Producer routing config for Recording API outputs. Topic keys are part of
 * `RecordingApiConfig` (picked from `SessionRecordingConfig`); only the
 * producer keys live here.
 */
export type RecordingApiOutputsConfig = {
    SESSION_REPLAY_OUTPUT_REPLAY_EVENTS_PRODUCER: SessionReplayProducerName
    SESSION_REPLAY_OUTPUT_SESSION_FEATURES_PRODUCER: SessionReplayProducerName
}

export function getDefaultRecordingApiOutputsConfig(): RecordingApiOutputsConfig {
    return {
        SESSION_REPLAY_OUTPUT_REPLAY_EVENTS_PRODUCER: DEFAULT_PRODUCER,
        SESSION_REPLAY_OUTPUT_SESSION_FEATURES_PRODUCER: DEFAULT_PRODUCER,
    }
}

export interface RecordingBlock {
    key: string
    start_byte: number
    end_byte: number
    start_timestamp: string
    end_timestamp: string
}
