import { KeyStore, RecordingEncryptor, SessionKey } from '../types'

/**
 * Cleartext encryptor used for hobby deployments and local development instances.
 * Returns data unchanged since sessions are not encrypted.
 */
export class CleartextRecordingEncryptor implements RecordingEncryptor {
    constructor(_keyStore: KeyStore) {}

    start(): Promise<void> {
        return Promise.resolve()
    }

    encryptBlock(_sessionId: string, _teamId: number, blockData: Buffer): Promise<Buffer> {
        return Promise.resolve(blockData)
    }

    encryptBlockWithKey(_sessionId: string, _teamId: number, blockData: Buffer, _sessionKey: SessionKey): Buffer {
        return blockData
    }
}
