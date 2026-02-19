import sodium from 'libsodium-wrappers'

import { KeyStore, RecordingDecryptor, SessionKey, SessionKeyDeletedError } from '../types'

export class SodiumRecordingDecryptor implements RecordingDecryptor {
    constructor(private keyStore: KeyStore) {}

    async start(): Promise<void> {
        await sodium.ready
    }

    async decryptBlock(sessionId: string, teamId: number, blockData: Buffer): Promise<Buffer> {
        const sessionKey = await this.keyStore.getKey(sessionId, teamId)
        return this.decryptBlockWithKey(sessionId, teamId, blockData, sessionKey)
    }

    decryptBlockWithKey(sessionId: string, teamId: number, blockData: Buffer, sessionKey: SessionKey): Buffer {
        if (sessionKey.sessionState === 'deleted') {
            throw new SessionKeyDeletedError(sessionId, teamId, sessionKey.deletedAt)
        }

        if (sessionKey.sessionState === 'cleartext') {
            return blockData // Session is stored in cleartext, do not decrypt
        }

        // Extract nonce from the beginning of the block (prepended during encryption)
        const nonce = blockData.subarray(0, sodium.crypto_secretbox_NONCEBYTES)
        const cipherText = blockData.subarray(sodium.crypto_secretbox_NONCEBYTES)

        const clearText = sodium.crypto_secretbox_open_easy(cipherText, nonce, sessionKey.plaintextKey)
        return Buffer.from(clearText)
    }
}
