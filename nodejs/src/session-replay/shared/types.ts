/**
 * Shared Session Replay Encryption Types
 *
 * Types used by both the ingestion pipeline (session-recording/) and the
 * Recording API (session-replay/recording-api/).
 *
 * Each session recording is encrypted with a unique per-session key. When a recording
 * needs to be deleted (e.g., for GDPR compliance), we delete the key rather than the
 * recording data itself (crypto-shredding).
 */

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
    /** Identity (email) of who deleted this key, if sessionState is 'deleted' */
    deletedBy?: string
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
    deletedBy?: string
}

/**
 * Interface for managing session encryption keys.
 * Implementations include DynamoDB (cloud) and cleartext (self-hosted).
 */
export type DeleteKeyResult =
    | { status: 'deleted'; deletedAt: number; deletedBy: string }
    | { status: 'already_deleted'; deletedAt: number; deletedBy: string }

export interface KeyStore {
    start(): Promise<void>
    /** Generate and store a new encryption key for a session */
    generateKey(sessionId: string, teamId: number): Promise<SessionKey>
    /** Retrieve the encryption key for a session */
    getKey(sessionId: string, teamId: number): Promise<SessionKey>
    /** Delete a session's key (crypto-shredding) */
    deleteKey(sessionId: string, teamId: number, deletedBy: string): Promise<DeleteKeyResult>
    stop(): void
}

/**
 * Interface for encrypting recording blocks.
 * Used during ingestion to encrypt recording data before storage.
 */
export interface RecordingEncryptor {
    start(): Promise<void>
    /** Encrypt a block, fetching the session key automatically */
    encryptBlock(sessionId: string, teamId: number, blockData: Buffer): Promise<EncryptResult>
    /** Encrypt a block with a pre-fetched session key */
    encryptBlockWithKey(sessionId: string, teamId: number, blockData: Buffer, sessionKey: SessionKey): EncryptResult
}

/**
 * Interface for decrypting recording blocks.
 * Used by the Recording API to decrypt data when serving playback requests.
 */
export interface RecordingDecryptor {
    start(): Promise<void>
    /** Decrypt a block, fetching the session key automatically */
    decryptBlock(sessionId: string, teamId: number, blockData: Buffer): Promise<DecryptResult>
    /** Decrypt a block with a pre-fetched session key */
    decryptBlockWithKey(sessionId: string, teamId: number, blockData: Buffer, sessionKey: SessionKey): DecryptResult
}

/**
 * Error thrown when attempting to access a crypto-shredded session.
 * The recording data still exists but is permanently unreadable.
 */
export interface EncryptResult {
    data: Buffer
    sessionState: SessionState
}

export interface DecryptResult {
    data: Buffer
    sessionState: SessionState
}

export class SessionKeyDeletedError extends Error {
    public readonly deletedAt?: number
    public readonly deletedBy: string

    constructor(sessionId: string, teamId: number, deletedAt?: number, deletedBy: string = '') {
        super(`Session key has been deleted for session ${sessionId} team ${teamId}`)
        this.name = 'SessionKeyDeletedError'
        this.deletedAt = deletedAt
        this.deletedBy = deletedBy
    }
}
