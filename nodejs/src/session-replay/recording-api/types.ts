/**
 * Recording API Types
 *
 * Re-exports shared encryption types from session-replay/types.ts and adds
 * Recording API-specific types.
 */
import { Hub } from '../../types'

// Re-export all shared encryption types so existing recording-api imports still work
export {
    DeleteKeyResult,
    KeyStore,
    RecordingDecryptor,
    RecordingEncryptor,
    SerializedSessionKey,
    SessionKey,
    SessionKeyDeletedError,
    SessionState,
} from '../types'

/**
 * Subset of Hub configuration required by the Recording API.
 */
export type RecordingApiHub = Pick<
    Hub,
    | 'postgres'
    | 'KAFKA_CLIENT_RACK'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
    | 'SESSION_RECORDING_API_REDIS_HOST'
    | 'SESSION_RECORDING_API_REDIS_PORT'
    | 'SESSION_RECORDING_V2_S3_REGION'
    | 'SESSION_RECORDING_V2_S3_ENDPOINT'
    | 'SESSION_RECORDING_V2_S3_ACCESS_KEY_ID'
    | 'SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY'
    | 'SESSION_RECORDING_V2_S3_BUCKET'
    | 'SESSION_RECORDING_V2_S3_PREFIX'
    | 'SESSION_RECORDING_KMS_ENDPOINT'
    | 'SESSION_RECORDING_DYNAMODB_ENDPOINT'
>
