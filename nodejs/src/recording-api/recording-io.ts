import sodium from 'libsodium-wrappers'

import { isCloud } from '../utils/env-utils'
import { BaseKeyStore } from './keystore'

export abstract class BaseRecordingEncryptor {
    abstract start(): Promise<void>
    abstract encryptBlock(sessionId: string, teamId: number, clearText: Buffer): Promise<Buffer>
}

export abstract class BaseRecordingDecryptor {
    abstract start(): Promise<void>
    abstract decryptBlock(sessionId: string, teamId: number, cipherText: Buffer): Promise<Buffer>
}

export class PassthroughRecordingEncryptor extends BaseRecordingEncryptor {
    constructor(_keyStore: BaseKeyStore) {
        super()
    }

    start(): Promise<void> {
        return Promise.resolve()
    }

    encryptBlock(_sessionId: string, _teamId: number, clearText: Buffer): Promise<Buffer> {
        return Promise.resolve(clearText)
    }
}

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

export class SessionKeyDeletedError extends Error {
    constructor(sessionId: string, teamId: number) {
        super(`Session key has been deleted for session ${sessionId} team ${teamId}`)
        this.name = 'SessionKeyDeletedError'
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

        if (sessionKey.sessionState === 'deleted') {
            throw new SessionKeyDeletedError(sessionId, teamId) // Session was deleted
        }

        if (sessionKey.sessionState === 'cleartext') {
            return blockData // Session is stored in cleartext, do not encrypt
        }

        // Session is encrypted, so encrypt block and return
        const cipherText = sodium.crypto_secretbox_easy(blockData, sessionKey.nonce, sessionKey.plaintextKey)
        return Buffer.from(cipherText)
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
            throw new SessionKeyDeletedError(sessionId, teamId) // Session was deleted
        }

        if (sessionKey.sessionState === 'cleartext') {
            return blockData // Session is stored in cleartext, do not decrypt
        }

        // Session is encrypted, decrypt and return
        const clearText = sodium.crypto_secretbox_open_easy(blockData, sessionKey.nonce, sessionKey.plaintextKey)
        return Buffer.from(clearText)
    }
}

export function getBlockEncryptor(keyStore: BaseKeyStore): BaseRecordingEncryptor {
    if (isCloud()) {
        return new RecordingEncryptor(keyStore)
    }
    return new PassthroughRecordingEncryptor(keyStore)
}

export function getBlockDecryptor(keyStore: BaseKeyStore): BaseRecordingDecryptor {
    if (isCloud()) {
        return new RecordingDecryptor(keyStore)
    }
    return new PassthroughRecordingDecryptor(keyStore)
}
