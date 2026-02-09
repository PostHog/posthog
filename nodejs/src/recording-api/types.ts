import { Hub } from '../types'

export type RecordingApiHub = Pick<
    Hub,
    | 'postgres'
    | 'REDIS_URL'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
    | 'SESSION_RECORDING_V2_S3_REGION'
    | 'SESSION_RECORDING_V2_S3_ENDPOINT'
    | 'SESSION_RECORDING_V2_S3_ACCESS_KEY_ID'
    | 'SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY'
    | 'SESSION_RECORDING_V2_S3_BUCKET'
    | 'SESSION_RECORDING_V2_S3_PREFIX'
    | 'SESSION_RECORDING_KMS_ENDPOINT'
    | 'SESSION_RECORDING_DYNAMODB_ENDPOINT'
>

export type SessionState = 'ciphertext' | 'cleartext' | 'deleted'

export interface SessionKey {
    plaintextKey: Buffer
    encryptedKey: Buffer
    sessionState: SessionState
    deletedAt?: number
}

export interface SerializedSessionKey {
    plaintextKey: string
    encryptedKey: string
    sessionState: SessionState
    deletedAt?: number
}

export interface KeyStore {
    start(): Promise<void>
    generateKey(sessionId: string, teamId: number): Promise<SessionKey>
    getKey(sessionId: string, teamId: number): Promise<SessionKey>
    deleteKey(sessionId: string, teamId: number): Promise<boolean>
    stop(): void
}

export interface RecordingEncryptor {
    start(): Promise<void>
    encryptBlock(sessionId: string, teamId: number, blockData: Buffer): Promise<Buffer>
    encryptBlockWithKey(sessionId: string, teamId: number, blockData: Buffer, sessionKey: SessionKey): Buffer
}

export interface RecordingDecryptor {
    start(): Promise<void>
    decryptBlock(sessionId: string, teamId: number, blockData: Buffer): Promise<Buffer>
    decryptBlockWithKey(sessionId: string, teamId: number, blockData: Buffer, sessionKey: SessionKey): Buffer
}

export class SessionKeyDeletedError extends Error {
    public readonly deletedAt?: number

    constructor(sessionId: string, teamId: number, deletedAt?: number) {
        super(`Session key has been deleted for session ${sessionId} team ${teamId}`)
        this.name = 'SessionKeyDeletedError'
        this.deletedAt = deletedAt
    }
}
