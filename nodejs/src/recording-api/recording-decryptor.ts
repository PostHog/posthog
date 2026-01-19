import sodium from 'libsodium-wrappers'

import { isCloud } from '../utils/env-utils'
import { BaseKeyStore, BaseRecordingDecryptor, SessionKeyDeletedError } from './types'

export class PassthroughRecordingDecryptor extends BaseRecordingDecryptor {
    constructor(_keyStore: BaseKeyStore) {
        super()
    }

    start(): Promise<void> {
        return Promise.resolve()
    }

    decryptBlock(_sessionId: string, _teamId: number, cipherText: Buffer): Promise<Buffer> {
        return Promise.resolve(cipherText)
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

        if (sessionKey.sessionState === 'deleted') {
            throw new SessionKeyDeletedError(sessionId, teamId, sessionKey.deletedAt ?? 0)
        }

        if (sessionKey.sessionState === 'cleartext') {
            return blockData // Session is stored in cleartext, do not decrypt
        }

        // Session is encrypted, decrypt and return
        const clearText = sodium.crypto_secretbox_open_easy(blockData, sessionKey.nonce, sessionKey.plaintextKey)
        return Buffer.from(clearText)
    }
}

export function getBlockDecryptor(keyStore: BaseKeyStore): BaseRecordingDecryptor {
    if (isCloud()) {
        return new RecordingDecryptor(keyStore)
    }
    return new PassthroughRecordingDecryptor(keyStore)
}
