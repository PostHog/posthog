import { DecryptCommand, GenerateDataKeyCommand, KMSClient } from '@aws-sdk/client-kms'
import { LRUCache } from 'lru-cache'
import { createCipheriv, createDecipheriv, hkdfSync, randomBytes } from 'node:crypto'
import pLimit from 'p-limit'

import { MlKeyRequest, MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'

import { MlKeyIdentity, wrappingContext } from './schema'

export interface MlDataKey {
    identity: MlKeyIdentity
    plaintext: Buffer
    wrapped: Buffer
}

/** The raw payload sealed with AES-256-GCM; the canonical JSON of `{ v, context }` is the additional authenticated data. */
export interface MlEncryptedEnvelope {
    v: 3
    context: MlKeyIdentity & { kind: string; ref?: string }
    nonce: string
    ciphertext: string
}

export const NONCE_BYTES = 12
export const TAG_BYTES = 16

/** Both readers rebuild this byte for byte, so key order is sorted and there is no whitespace. */
export function canonicalJson(value: unknown): string {
    if (Array.isArray(value)) {
        return `[${value.map(canonicalJson).join(',')}]`
    }
    if (value && typeof value === 'object') {
        return `{${Object.keys(value)
            .sort()
            .map((k) => `${JSON.stringify(k)}:${canonicalJson((value as Record<string, unknown>)[k])}`)
            .join(',')}}`
    }
    return JSON.stringify(value)
}

export interface MlSealedKey {
    sealed: Buffer
    nonce: Buffer
}

// HKDF makes this key from the stored key, which also seals image data. One key with two jobs lets a flaw in one job
// reach the other.
const SESSION_WRAP_INFO = Buffer.from('ml-session-key-wrap')

function sessionWrappingKey(teamMonthKey: Buffer): Buffer {
    return Buffer.from(hkdfSync('sha256', teamMonthKey, Buffer.alloc(0), SESSION_WRAP_INFO, 32))
}

/** The seal authenticates the identity, so a sealed key cannot move to another session or another team. */
export function sealSessionKey(teamMonthKey: Buffer, identity: MlKeyIdentity, plaintext: Buffer): MlSealedKey {
    const nonce = randomBytes(NONCE_BYTES)
    const cipher = createCipheriv('aes-256-gcm', sessionWrappingKey(teamMonthKey), nonce, { authTagLength: TAG_BYTES })
    cipher.setAAD(Buffer.from(canonicalJson(wrappingContext(identity))))
    return { sealed: Buffer.concat([cipher.update(plaintext), cipher.final(), cipher.getAuthTag()]), nonce }
}

export function openSessionKey(teamMonthKey: Buffer, identity: MlKeyIdentity, sealed: MlSealedKey): Buffer {
    if (sealed.sealed.length <= TAG_BYTES) {
        throw new Error('ML sealed session key is too short')
    }
    const body = sealed.sealed.subarray(0, sealed.sealed.length - TAG_BYTES)
    const tag = sealed.sealed.subarray(sealed.sealed.length - TAG_BYTES)
    const decipher = createDecipheriv('aes-256-gcm', sessionWrappingKey(teamMonthKey), sealed.nonce, {
        authTagLength: TAG_BYTES,
    })
    decipher.setAAD(Buffer.from(canonicalJson(wrappingContext(identity))))
    decipher.setAuthTag(tag)
    return Buffer.concat([decipher.update(body), decipher.final()])
}

export class MlKeyEncryption {
    private readonly cache: LRUCache<string, Buffer>
    private readonly pending = new Map<string, Promise<Buffer>>()
    private readonly concurrency: ReturnType<typeof pLimit>
    private nextRequestAt = 0

    constructor(
        private readonly kms: Pick<KMSClient, 'send'>,
        private readonly masterKeyArn: string,
        maxKeys = 100_000,
        cacheLifetimeMs = 1_800_000,
        concurrency = 8,
        private readonly requestsPerSecond = 150
    ) {
        this.cache = new LRUCache({ max: maxKeys, ttl: cacheLifetimeMs })
        this.concurrency = pLimit(concurrency)
        if (requestsPerSecond <= 0) {
            throw new Error('ML KMS request rate must be positive')
        }
    }

    private async request<T>(kind: MlKeyRequest, operation: () => Promise<T>): Promise<T> {
        return this.concurrency(async () => {
            const queuedAt = performance.now()
            const now = Date.now()
            const scheduledAt = Math.max(now, this.nextRequestAt)
            this.nextRequestAt = scheduledAt + 1000 / this.requestsPerSecond
            if (scheduledAt > now) {
                await new Promise((resolve) => setTimeout(resolve, scheduledAt - now))
            }
            const sentAt = performance.now()
            MlMirrorMetrics.observeMlKeyRequest('kms_wait', sentAt - queuedAt)
            try {
                return await operation()
            } finally {
                MlMirrorMetrics.observeMlKeyRequest(kind, performance.now() - sentAt)
            }
        })
    }

    public async generate(identity: MlKeyIdentity): Promise<MlDataKey> {
        const result = await this.request('kms_generate', () =>
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
        if (!key.wrapped.length) {
            return
        }
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
            pending = this.request('kms_decrypt', async () => {
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

/** Names how the reader must expand the plaintext. It sits inside the authenticated context so it cannot be downgraded. */
export type MlEnvelopeCodec = 'none' | 'brotli'

const ENVELOPE_MAGIC = Buffer.from('AISR03')
const AAD_LENGTH_BYTES = 2

/**
 * Frames the ciphertext as raw bytes rather than base64 in JSON, which stores a quarter fewer bytes for the same payload.
 * The frame carries the additional authenticated data verbatim, so a reader authenticates against the bytes we signed
 * instead of rebuilding canonical JSON of its own.
 */
export function encryptEnvelope(
    key: MlDataKey,
    kind: string,
    body: Buffer,
    options: { ref?: string; codec: MlEnvelopeCodec }
): Buffer {
    const context = { ...key.identity, kind, codec: options.codec, ...(options.ref ? { ref: options.ref } : {}) }
    const aad = Buffer.from(canonicalJson({ v: 3, context }))
    if (aad.length > 0xffff) {
        throw new Error('ML envelope context is too long to frame')
    }
    const nonce = randomBytes(NONCE_BYTES)
    const cipher = createCipheriv('aes-256-gcm', key.plaintext, nonce, { authTagLength: TAG_BYTES })
    cipher.setAAD(aad)
    const ciphertext = Buffer.concat([cipher.update(body), cipher.final(), cipher.getAuthTag()])
    const header = Buffer.allocUnsafe(AAD_LENGTH_BYTES)
    header.writeUInt16BE(aad.length)
    return Buffer.concat([ENVELOPE_MAGIC, header, aad, nonce, ciphertext])
}

/** Base64 in JSON, for the parquet columns that hold a value rather than an object body. */
export function encryptEnvelopeJson(key: MlDataKey, kind: string, data: Buffer, ref?: string): MlEncryptedEnvelope {
    const context = { ...key.identity, kind, ...(ref ? { ref } : {}) }
    const nonce = randomBytes(NONCE_BYTES)
    const cipher = createCipheriv('aes-256-gcm', key.plaintext, nonce, { authTagLength: TAG_BYTES })
    cipher.setAAD(Buffer.from(canonicalJson({ v: 3, context })))
    const ciphertext = Buffer.concat([cipher.update(data), cipher.final(), cipher.getAuthTag()])
    return { v: 3, context, nonce: nonce.toString('base64'), ciphertext: ciphertext.toString('base64') }
}
