import sodium from 'libsodium-wrappers'

import { KeyStore, RecordingEncryptor, SessionKey, SessionKeyDeletedError } from '../types'

export class SodiumRecordingEncryptor implements RecordingEncryptor {
    constructor(private keyStore: KeyStore) {}

    async start(): Promise<void> {
        await sodium.ready
    }

    async encryptBlock(sessionId: string, teamId: number, blockData: Buffer): Promise<Buffer> {
        const sessionKey = await this.keyStore.getKey(sessionId, teamId)
        return this.encryptBlockWithKey(sessionId, teamId, blockData, sessionKey)
    }

    encryptBlockWithKey(sessionId: string, teamId: number, blockData: Buffer, sessionKey: SessionKey): Buffer {
        if (sessionKey.sessionState === 'deleted') {
            throw new SessionKeyDeletedError(sessionId, teamId, sessionKey.deletedAt)
        }

        if (sessionKey.sessionState === 'cleartext') {
            return blockData // Session is stored in cleartext, do not encrypt
        }

        // Generate a unique nonce for this block
        const nonce = sodium.randombytes_buf(sodium.crypto_secretbox_NONCEBYTES)

        // Encrypt block data
        const cipherText = sodium.crypto_secretbox_easy(blockData, nonce, sessionKey.plaintextKey)

        // Prepend nonce to the ciphertext
        return Buffer.concat([Buffer.from(nonce), Buffer.from(cipherText)])
    }
}
