import sodium from 'libsodium-wrappers'

import { isCloud } from '../utils/env-utils'
import { BaseKeyStore } from './keystore'

export abstract class BaseRecordingEncryptor {
    abstract encryptBlock(sessionId: string, teamId: number, clearText: Buffer): Promise<Buffer>
}

export abstract class BaseRecordingDecryptor {
    abstract decryptBlock(sessionId: string, teamId: number, cipherText: Buffer): Promise<Buffer>
}

export class PassthroughRecordingEncryptor extends BaseRecordingEncryptor {
    constructor(_keyStore: BaseKeyStore) {
        super()
    }

    encryptBlock(_sessionId: string, _teamId: number, clearText: Buffer): Promise<Buffer> {
        return Promise.resolve(clearText)
    }
}

export class PassthroughRecordingDecryptor extends BaseRecordingDecryptor {
    constructor(_keyStore: BaseKeyStore) {
        super()
    }

    decryptBlock(_sessionId: string, _teamId: number, cipherText: Buffer): Promise<Buffer> {
        return Promise.resolve(cipherText)
    }
}

export class RecordingEncryptor extends BaseRecordingEncryptor {
    private keyStore: BaseKeyStore

    private constructor(keyStore: BaseKeyStore) {
        super()
        this.keyStore = keyStore
    }

    static async create(keyStore: BaseKeyStore): Promise<RecordingEncryptor> {
        await sodium.ready
        return new RecordingEncryptor(keyStore)
    }

    async encryptBlock(sessionId: string, teamId: number, clearText: Buffer): Promise<Buffer> {
        const sessionKey = await this.keyStore.getKey(sessionId, teamId)
        const cipherText = sodium.crypto_secretbox_easy(clearText, sessionKey.nonce, sessionKey.plaintextKey)
        return Buffer.from(cipherText)
    }
}

export class RecordingDecryptor extends BaseRecordingDecryptor {
    private keyStore: BaseKeyStore

    private constructor(keyStore: BaseKeyStore) {
        super()
        this.keyStore = keyStore
    }

    static async create(keyStore: BaseKeyStore): Promise<RecordingDecryptor> {
        await sodium.ready
        return new RecordingDecryptor(keyStore)
    }

    async decryptBlock(sessionId: string, teamId: number, cipherText: Buffer): Promise<Buffer> {
        const sessionKey = await this.keyStore.getKey(sessionId, teamId)
        const clearText = sodium.crypto_secretbox_open_easy(cipherText, sessionKey.nonce, sessionKey.plaintextKey)
        return Buffer.from(clearText)
    }
}

export async function getBlockEncryptor(keyStore: BaseKeyStore): Promise<BaseRecordingEncryptor> {
    if (isCloud()) {
        return RecordingEncryptor.create(keyStore)
    }
    return new PassthroughRecordingEncryptor(keyStore)
}

export async function getBlockDecryptor(keyStore: BaseKeyStore): Promise<BaseRecordingDecryptor> {
    if (isCloud()) {
        return RecordingDecryptor.create(keyStore)
    }
    return new PassthroughRecordingDecryptor(keyStore)
}
