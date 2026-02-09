import sodium from 'libsodium-wrappers'

import { KeyStore, SessionKey, SessionKeyDeletedError } from '../types'

/**
 * In-memory key store for testing purposes.
 * Generates real encryption keys using libsodium.
 */
export class MemoryKeyStore implements KeyStore {
    private keystore = new Map<string, SessionKey>()
    private deletedKeys = new Map<string, number>()

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

    async getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const deletedAt = this.deletedKeys.get(`${teamId}:${sessionId}`)
        if (deletedAt) {
            throw new SessionKeyDeletedError(sessionId, teamId, deletedAt)
        }

        const sessionKey = this.keystore.get(`${teamId}:${sessionId}`)
        if (!sessionKey) {
            return this.generateKey(sessionId, teamId)
        }
        return sessionKey
    }

    deleteKey(sessionId: string, teamId: number): Promise<boolean> {
        if (this.keystore.has(`${teamId}:${sessionId}`)) {
            this.keystore.delete(`${teamId}:${sessionId}`)
            this.deletedKeys.set(`${teamId}:${sessionId}`, Date.now())
            return Promise.resolve(true)
        }
        return Promise.resolve(false)
    }

    stop(): void {}
}
