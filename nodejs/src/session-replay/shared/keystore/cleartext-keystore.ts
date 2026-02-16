import { DeleteKeyResult, KeyStore, SessionKey } from '../types'

/**
 * Cleartext key store used for hobby deployments and local development instances.
 * Returns empty keys and treats all sessions as cleartext (unencrypted).
 */
export class CleartextKeyStore implements KeyStore {
    start(): Promise<void> {
        return Promise.resolve()
    }

    generateKey(_sessionId: string, _teamId: number): Promise<SessionKey> {
        return Promise.resolve({
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            sessionState: 'cleartext',
        })
    }

    getKey(_sessionId: string, _teamId: number): Promise<SessionKey> {
        return Promise.resolve({
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            sessionState: 'cleartext',
        })
    }

    deleteKey(_sessionId: string, _teamId: number): Promise<DeleteKeyResult> {
        // Crypto-shredding is not supported for cleartext sessions (non-cloud deployments)
        return Promise.resolve({ deleted: false, reason: 'not_supported' })
    }

    stop(): void {}
}
