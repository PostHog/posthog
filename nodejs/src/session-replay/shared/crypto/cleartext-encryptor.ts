import { EncryptResult, KeyStore, RecordingEncryptor, SessionKey } from '../types'

/**
 * Cleartext encryptor used for hobby deployments and local development instances.
 * Returns data unchanged since sessions are not encrypted.
 */
export class CleartextRecordingEncryptor implements RecordingEncryptor {
    constructor(_keyStore: KeyStore) {}

    start(): Promise<void> {
        return Promise.resolve()
    }

    encryptBlock(_sessionId: string, _teamId: number, blockData: Buffer): Promise<EncryptResult> {
        return Promise.resolve({ data: blockData, sessionState: 'cleartext' })
    }

    encryptBlockWithKey(
        _sessionId: string,
        _teamId: number,
        blockData: Buffer,
        _sessionKey: SessionKey
    ): EncryptResult {
        return { data: blockData, sessionState: 'cleartext' }
    }
}
