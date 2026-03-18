import sodium from 'libsodium-wrappers'

import { DeleteKeyResult, KeyStore, SessionKey } from '../types'

/**
 * In-memory key store for testing purposes.
 * Generates real encryption keys using libsodium.
 */
export class MemoryKeyStore implements KeyStore {
    private keystore = new Map<string, SessionKey>()
    private deletedKeys = new Map<string, { deletedAt: number; deletedBy: string }>()

    async start(): Promise<void> {
        await sodium.ready
    }

    generateKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const plaintextKey = Buffer.from(sodium.crypto_secretbox_keygen())
        const sessionKey: SessionKey = {
            plaintextKey,
            encryptedKey: plaintextKey,
            sessionState: 'ciphertext',
        }
        this.keystore.set(`${teamId}:${sessionId}`, sessionKey)
        return Promise.resolve(sessionKey)
    }

    getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const deleted = this.deletedKeys.get(`${teamId}:${sessionId}`)
        if (deleted) {
            return Promise.resolve({
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                sessionState: 'deleted',
                deletedAt: deleted.deletedAt,
                deletedBy: deleted.deletedBy,
            })
        }

        const sessionKey = this.keystore.get(`${teamId}:${sessionId}`)
        if (!sessionKey) {
            return Promise.resolve({
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                sessionState: 'cleartext',
            })
        }
        return Promise.resolve(sessionKey)
    }

    deleteKey(sessionId: string, teamId: number, deletedBy: string): Promise<DeleteKeyResult> {
        const existing = this.deletedKeys.get(`${teamId}:${sessionId}`)
        if (existing) {
            return Promise.resolve({
                status: 'already_deleted',
                deletedAt: existing.deletedAt,
                deletedBy: existing.deletedBy,
            })
        }
        this.keystore.delete(`${teamId}:${sessionId}`)
        const deletedAt = Math.floor(Date.now() / 1000)
        this.deletedKeys.set(`${teamId}:${sessionId}`, { deletedAt, deletedBy })
        return Promise.resolve({ status: 'deleted', deletedAt, deletedBy })
    }

    stop(): void {}
}
