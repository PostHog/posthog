import sodium from 'libsodium-wrappers'

import { isCloud } from '../utils/env-utils'
import { BaseKeyStore, BaseRecordingDecryptor, SessionKey, SessionKeyDeletedError } from './types'

export class PassthroughRecordingDecryptor extends BaseRecordingDecryptor {
    constructor(_keyStore: BaseKeyStore) {
        super()
    }

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

export class RecordingDecryptor extends BaseRecordingDecryptor {
    constructor(private keyStore: BaseKeyStore) {
        super()
    }

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

export function getBlockDecryptor(keyStore: BaseKeyStore): BaseRecordingDecryptor {
    if (isCloud()) {
        return new RecordingDecryptor(keyStore)
    }
    return new PassthroughRecordingDecryptor(keyStore)
}
