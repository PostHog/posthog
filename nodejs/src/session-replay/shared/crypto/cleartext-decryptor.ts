import { KeyStore, RecordingDecryptor, SessionKey } from '../types'

/**
 * Cleartext decryptor used for hobby deployments and local development instances.
 * Returns data unchanged since sessions are not encrypted.
 */
export class CleartextRecordingDecryptor implements RecordingDecryptor {
    constructor(_keyStore: KeyStore) {}

    start(): Promise<void> {
        return Promise.resolve()
    }

    decryptBlock(_sessionId: string, _teamId: number, blockData: Buffer): Promise<Buffer> {
        return Promise.resolve(blockData)
    }

    decryptBlockWithKey(_sessionId: string, _teamId: number, blockData: Buffer, _sessionKey: SessionKey): Buffer {
        return blockData
    }
}
