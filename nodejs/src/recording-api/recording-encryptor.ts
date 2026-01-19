import sodium from 'libsodium-wrappers'

import { isCloud } from '../utils/env-utils'
import { BaseKeyStore, BaseRecordingEncryptor, SessionKey, SessionKeyDeletedError } from './types'

export class PassthroughRecordingEncryptor extends BaseRecordingEncryptor {
    constructor(_keyStore: BaseKeyStore) {
        super()
    }

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

export class RecordingEncryptor extends BaseRecordingEncryptor {
    constructor(private keyStore: BaseKeyStore) {
        super()
    }

    async start(): Promise<void> {
        await sodium.ready
    }

    async encryptBlock(sessionId: string, teamId: number, blockData: Buffer): Promise<Buffer> {
        const sessionKey = await this.keyStore.getKey(sessionId, teamId)
        return this.encryptBlockWithKey(sessionId, teamId, blockData, sessionKey)
    }

    encryptBlockWithKey(sessionId: string, teamId: number, blockData: Buffer, sessionKey: SessionKey): Buffer {
        if (sessionKey.sessionState === 'deleted') {
            throw new SessionKeyDeletedError(sessionId, teamId, sessionKey.deletedAt ?? 0)
        }

        if (sessionKey.sessionState === 'cleartext') {
            return blockData // Session is stored in cleartext, do not encrypt
        }

        // Session is encrypted, so encrypt block and return
        const cipherText = sodium.crypto_secretbox_easy(blockData, sessionKey.nonce, sessionKey.plaintextKey)
        return Buffer.from(cipherText)
    }
}

export function getBlockEncryptor(keyStore: BaseKeyStore): BaseRecordingEncryptor {
    if (isCloud()) {
        return new RecordingEncryptor(keyStore)
    }
    return new PassthroughRecordingEncryptor(keyStore)
}
