/**
 * Recording API Types
 *
 * Each session recording is encrypted with a unique per-session key. When a recording
 * needs to be deleted (e.g., for GDPR compliance), we delete the key rather than the
 * recording data itself (crypto-shredding).
 */
import { Hub } from '../types'

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

/**
 * The encryption state of a session recording.
 * - 'ciphertext': Recording is encrypted (cloud deployments)
 * - 'cleartext': Recording is stored unencrypted (self-hosted/hobby deployments)
 * - 'deleted': Encryption key has been deleted via crypto-shredding; recording is unreadable
 */
export type SessionState = 'ciphertext' | 'cleartext' | 'deleted'

/**
 * Encryption key for a session recording.
 * Each session has a unique key stored in DynamoDB, with the plaintext key
 * encrypted at rest using AWS KMS.
 */
export interface SessionKey {
    /** The decrypted key used for encrypting/decrypting recording blocks */
    plaintextKey: Buffer
    /** The KMS-encrypted version of the key (stored in DynamoDB) */
    encryptedKey: Buffer
    /** Current state of this session's encryption */
    sessionState: SessionState
    /** Unix timestamp (seconds) when the key was deleted, if sessionState is 'deleted' */
    deletedAt?: number
}

/**
 * JSON-serializable version of SessionKey for caching in Redis.
 * Buffer fields are base64-encoded strings.
 */
export interface SerializedSessionKey {
    plaintextKey: string
    encryptedKey: string
    sessionState: SessionState
    deletedAt?: number
}

/**
 * Interface for managing session encryption keys.
 * Implementations include DynamoDB (cloud) and cleartext (self-hosted).
 */
export type DeleteKeyResult =
    | { deleted: true }
    | { deleted: false; reason: 'not_found' }
    | { deleted: false; reason: 'already_deleted'; deletedAt?: number }
    | { deleted: false; reason: 'not_supported' }

export interface KeyStore {
    start(): Promise<void>
    /** Generate and store a new encryption key for a session */
    generateKey(sessionId: string, teamId: number): Promise<SessionKey>
    /** Retrieve the encryption key for a session */
    getKey(sessionId: string, teamId: number): Promise<SessionKey>
    /** Delete a session's key (crypto-shredding) */
    deleteKey(sessionId: string, teamId: number): Promise<DeleteKeyResult>
    stop(): void
}

/**
 * Interface for encrypting recording blocks.
 * Used during ingestion to encrypt recording data before storage.
 */
export interface RecordingEncryptor {
    start(): Promise<void>
    /** Encrypt a block, fetching the session key automatically */
    encryptBlock(sessionId: string, teamId: number, blockData: Buffer): Promise<Buffer>
    /** Encrypt a block with a pre-fetched session key */
    encryptBlockWithKey(sessionId: string, teamId: number, blockData: Buffer, sessionKey: SessionKey): Buffer
}

/**
 * Interface for decrypting recording blocks.
 * Used by the Recording API to decrypt data when serving playback requests.
 */
export interface RecordingDecryptor {
    start(): Promise<void>
    /** Decrypt a block, fetching the session key automatically */
    decryptBlock(sessionId: string, teamId: number, blockData: Buffer): Promise<Buffer>
    /** Decrypt a block with a pre-fetched session key */
    decryptBlockWithKey(sessionId: string, teamId: number, blockData: Buffer, sessionKey: SessionKey): Buffer
}

/**
 * Error thrown when attempting to access a crypto-shredded session.
 * The recording data still exists but is permanently unreadable.
 */
export class SessionKeyDeletedError extends Error {
    public readonly deletedAt?: number

    constructor(sessionId: string, teamId: number, deletedAt?: number) {
        super(`Session key has been deleted for session ${sessionId} team ${teamId}`)
        this.name = 'SessionKeyDeletedError'
        this.deletedAt = deletedAt
    }
}
