import { DecryptResult, KeyStore, RecordingDecryptor, SessionKey } from '../types'

/**
 * Cleartext decryptor used for hobby deployments and local development instances.
 * Returns data unchanged since sessions are not encrypted.
 */
export class CleartextRecordingDecryptor implements RecordingDecryptor {
    constructor(_keyStore: KeyStore) {}

    start(): Promise<void> {
        return Promise.resolve()
    }

    decryptBlock(_sessionId: string, _teamId: number, blockData: Buffer): Promise<DecryptResult> {
        return Promise.resolve({ data: blockData, sessionState: 'cleartext' })
    }

    decryptBlockWithKey(
        _sessionId: string,
        _teamId: number,
        blockData: Buffer,
        _sessionKey: SessionKey
    ): DecryptResult {
        return { data: blockData, sessionState: 'cleartext' }
    }
}
