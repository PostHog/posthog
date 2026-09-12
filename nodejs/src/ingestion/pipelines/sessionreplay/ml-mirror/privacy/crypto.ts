import { DecryptCommand, GenerateDataKeyCommand, KMSClient } from '@aws-sdk/client-kms'
import sodium from 'libsodium-wrappers'
import { LRUCache } from 'lru-cache'
import { isDeepStrictEqual } from 'node:util'
import pLimit from 'p-limit'

import { parseJSON } from '~/common/utils/json-parse'

import { MlKeyIdentity, wrappingContext } from './schema'

export const KEY_READ_LEASE_MS = 300_000

export class MlKeyReadExpiredError extends Error {}

export interface MlDataKey {
    identity: MlKeyIdentity
    plaintext: Buffer
    wrapped: Buffer
    decryptUntil?: number
}

export interface MlEncryptedEnvelope {
    v: 2
    context: MlKeyIdentity & { kind: string; ref?: string }
    nonce: string
    ciphertext: string
}

export class MlKeyEncryption {
    private readonly cache: LRUCache<string, Buffer>
    private readonly pending = new Map<string, Promise<Buffer>>()
    private readonly concurrency: ReturnType<typeof pLimit>
    private nextRequestAt = 0

    constructor(
        private readonly kms: Pick<KMSClient, 'send'>,
        private readonly masterKeyArn: string,
        maxKeys = 10_000,
        cacheLifetimeMs = 60_000,
        concurrency = 8,
        private readonly requestsPerSecond = 100
    ) {
        this.cache = new LRUCache({ max: maxKeys, ttl: cacheLifetimeMs })
        this.concurrency = pLimit(concurrency)
        if (requestsPerSecond <= 0) {
            throw new Error('ML KMS request rate must be positive')
        }
    }

    public async start(): Promise<void> {
        await sodium.ready
    }

    private async request<T>(operation: () => Promise<T>): Promise<T> {
        return this.concurrency(async () => {
            const now = Date.now()
            const scheduledAt = Math.max(now, this.nextRequestAt)
            this.nextRequestAt = scheduledAt + 1000 / this.requestsPerSecond
            if (scheduledAt > now) {
                await new Promise((resolve) => setTimeout(resolve, scheduledAt - now))
            }
            return operation()
        })
    }

    public async generate(identity: MlKeyIdentity): Promise<MlDataKey> {
        const result = await this.request(() =>
            this.kms.send(
                new GenerateDataKeyCommand({
                    KeyId: this.masterKeyArn,
                    KeySpec: 'AES_256',
                    EncryptionContext: wrappingContext(identity),
                }),
                { abortSignal: AbortSignal.timeout(5000) }
            )
        )
        if (result.Plaintext?.length !== 32 || !result.CiphertextBlob?.length) {
            throw new Error('KMS returned an invalid ML data key')
        }
        return { identity, plaintext: Buffer.from(result.Plaintext), wrapped: Buffer.from(result.CiphertextBlob) }
    }

    public rememberCommitted(key: MlDataKey): void {
        this.cache.set(this.cacheId(key.identity, key.wrapped), key.plaintext)
    }

    private cacheId(identity: MlKeyIdentity, wrapped: Buffer): string {
        return JSON.stringify([wrappingContext(identity), wrapped.toString('base64')])
    }

    public async decrypt(identity: MlKeyIdentity, wrapped: Buffer): Promise<MlDataKey> {
        const id = this.cacheId(identity, wrapped)
        const cached = this.cache.get(id)
        if (cached) {
            return { identity, wrapped, plaintext: cached }
        }
        let pending = this.pending.get(id)
        if (!pending) {
            pending = this.request(async () => {
                const result = await this.kms.send(
                    new DecryptCommand({
                        KeyId: this.masterKeyArn,
                        CiphertextBlob: wrapped,
                        EncryptionContext: wrappingContext(identity),
                    }),
                    { abortSignal: AbortSignal.timeout(5000) }
                )
                if (result.Plaintext?.length !== 32) {
                    throw new Error('KMS returned an invalid ML plaintext key')
                }
                const plaintext = Buffer.from(result.Plaintext)
                this.cache.set(id, plaintext)
                return plaintext
            })
            this.pending.set(id, pending)
        }
        try {
            return { identity, wrapped, plaintext: await pending }
        } finally {
            if (this.pending.get(id) === pending) {
                this.pending.delete(id)
            }
        }
    }

    public clear(): void {
        this.cache.clear()
    }
}

export function encryptEnvelope(key: MlDataKey, kind: string, data: Buffer, ref?: string): Buffer {
    const context = { ...key.identity, kind, ...(ref ? { ref } : {}) }
    const nonce = sodium.randombytes_buf(sodium.crypto_secretbox_NONCEBYTES)
    const authenticated = Buffer.from(JSON.stringify({ context, data: data.toString('base64') }))
    const envelope: MlEncryptedEnvelope = {
        v: 2,
        context,
        nonce: Buffer.from(nonce).toString('base64'),
        ciphertext: Buffer.from(sodium.crypto_secretbox_easy(authenticated, nonce, key.plaintext)).toString('base64'),
    }
    return Buffer.from(JSON.stringify(envelope))
}

export function decryptEnvelope(key: MlDataKey, envelope: MlEncryptedEnvelope, kind: string, ref?: string): Buffer {
    if (key.decryptUntil !== undefined && performance.now() >= key.decryptUntil) {
        throw new MlKeyReadExpiredError('ML key read lease expired; read the key again')
    }
    const decoded: unknown = parseJSON(
        Buffer.from(
            sodium.crypto_secretbox_open_easy(
                Buffer.from(envelope.ciphertext, 'base64'),
                Buffer.from(envelope.nonce, 'base64'),
                key.plaintext
            )
        ).toString('utf8')
    )
    if (!decoded || typeof decoded !== 'object' || !('context' in decoded) || !('data' in decoded)) {
        throw new Error('Invalid authenticated ML envelope')
    }
    const context = { ...key.identity, kind, ...(ref ? { ref } : {}) }
    if (
        envelope.v !== 2 ||
        !isDeepStrictEqual(decoded.context, context) ||
        !isDeepStrictEqual(envelope.context, context) ||
        typeof decoded.data !== 'string'
    ) {
        throw new Error('ML envelope context mismatch')
    }
    return Buffer.from(decoded.data, 'base64')
}
