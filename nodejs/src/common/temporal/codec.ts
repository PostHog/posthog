import { PayloadCodec } from '@temporalio/common'
import { Payload as PayloadProto } from '@temporalio/common/lib/interfaces'
import { temporal } from '@temporalio/proto'
import * as crypto from 'crypto'

const ENCODING_KEY = 'encoding'
const ENCRYPTED_ENCODING = 'binary/encrypted'
const FERNET_VERSION = 0x80
const FERNET_HEADER_SIZE = 1 + 8 + 16 // version + timestamp + IV
const HMAC_SIZE = 32

type FernetKey = {
    signingKey: Buffer
    encryptionKey: Buffer
}

type RawSecretKey = string | Uint8Array

function decodeHex(secret: string): Buffer {
    const normalized = secret.replace(/\s/g, '')
    if (normalized.length % 2 !== 0 || !/^[0-9a-fA-F]*$/.test(normalized)) {
        throw new Error('EncryptionCodec: invalid hex secret key')
    }
    return Buffer.from(normalized, 'hex')
}

function decodeBase64(secret: string): Buffer {
    if (secret.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(secret)) {
        throw new Error('EncryptionCodec: invalid base64 secret key')
    }
    return Buffer.from(secret, 'base64')
}

function decodeBase64Urlsafe(secret: string): Buffer {
    if (secret.length % 4 !== 0 || !/^[A-Za-z0-9_-]*={0,2}$/.test(secret)) {
        throw new Error('EncryptionCodec: invalid base64-urlsafe secret key')
    }
    return Buffer.from(secret, 'base64url')
}

/**
 * Fernet-compatible encryption codec that matches PostHog's Python EncryptionCodec.
 *
 * The Python side (posthog/temporal/common/codec.py) derives each Fernet key by
 * zero-padding to 32 bytes, then base64url-encoding. The first 16 decoded bytes
 * are the HMAC-SHA256 signing key, and the last 16 are the AES-128-CBC key.
 */
export class EncryptionCodec implements PayloadCodec {
    private primaryKey: FernetKey
    private fallbackKeys: FernetKey[]

    constructor(secretKey: RawSecretKey, fallbackKeys: RawSecretKey[] = []) {
        this.primaryKey = this.prepareKey(secretKey)
        this.fallbackKeys = fallbackKeys.map((fallbackKey) => this.prepareKey(fallbackKey))
    }

    private loadAsBytes(raw: RawSecretKey): Buffer {
        if (raw instanceof Uint8Array) {
            return Buffer.from(raw)
        }

        const separatorIndex = raw.indexOf(':')
        if (separatorIndex === -1) {
            return Buffer.from(raw, 'utf-8')
        }

        const prefix = raw.slice(0, separatorIndex)
        const secret = raw.slice(separatorIndex + 1)

        switch (prefix) {
            case 'hex':
                return decodeHex(secret)
            case 'base64-urlsafe':
                return decodeBase64Urlsafe(secret)
            case 'base64':
                return decodeBase64(secret)
            default:
                // Legacy format, kept for compatibility with Python's _load_as_bytes.
                return Buffer.from(raw, 'utf-8')
        }
    }

    private prepareKey(secretKey: RawSecretKey): FernetKey {
        const keyBytes = this.loadAsBytes(secretKey)

        if (keyBytes.length === 0) {
            throw new Error('EncryptionCodec: empty secret key is not allowed')
        }

        if (keyBytes.length < 32 && process.env.NODE_ENV === 'production') {
            throw new Error(
                `EncryptionCodec: secret key must be at least 32 bytes in production (got ${keyBytes.length})`
            )
        }
        if (keyBytes.length < 32) {
            console.warn(
                `EncryptionCodec: secret key is only ${keyBytes.length} bytes; use a 32-byte key in production`
            )
        }

        // Match Python: pad with null bytes on the left, truncate to 32 bytes
        const padded = Buffer.alloc(32)
        if (keyBytes.length > 32) {
            console.warn(`EncryptionCodec: secret key is ${keyBytes.length} bytes, truncating to 32`)
        }
        const padLen = Math.max(32 - keyBytes.length, 0)
        keyBytes.copy(padded, padLen, 0, Math.min(keyBytes.length, 32))

        return {
            signingKey: padded.subarray(0, 16),
            encryptionKey: padded.subarray(16, 32),
        }
    }

    // eslint-disable-next-line @typescript-eslint/require-await
    async encode(payloads: PayloadProto[]): Promise<PayloadProto[]> {
        return payloads.map((p) => ({
            metadata: { [ENCODING_KEY]: new TextEncoder().encode(ENCRYPTED_ENCODING) },
            data: this.encrypt(temporal.api.common.v1.Payload.encode(p).finish()),
        }))
    }

    // eslint-disable-next-line @typescript-eslint/require-await
    async decode(payloads: PayloadProto[]): Promise<PayloadProto[]> {
        return payloads.map((p) => {
            const encoding = p.metadata?.[ENCODING_KEY]
            if (!encoding || new TextDecoder().decode(encoding) !== ENCRYPTED_ENCODING) {
                return p
            }
            const decrypted = this.decrypt(p.data as Uint8Array)
            return temporal.api.common.v1.Payload.decode(decrypted)
        })
    }

    private encrypt(data: Uint8Array): Uint8Array {
        const iv = crypto.randomBytes(16)
        const timestamp = BigInt(Math.floor(Date.now() / 1000))

        const cipher = crypto.createCipheriv('aes-128-cbc', this.primaryKey.encryptionKey, iv)
        const ciphertext = Buffer.concat([cipher.update(data), cipher.final()])

        // Fernet token: version || timestamp (big-endian 64-bit) || IV || ciphertext
        const body = Buffer.alloc(FERNET_HEADER_SIZE + ciphertext.length)
        body[0] = FERNET_VERSION
        body.writeBigUInt64BE(timestamp, 1)
        iv.copy(body, 9)
        ciphertext.copy(body, FERNET_HEADER_SIZE)

        const hmac = crypto.createHmac('sha256', this.primaryKey.signingKey).update(body).digest()
        const raw = Buffer.concat([body, hmac])

        // Python's Fernet expects base64url with padding — use standard base64
        // (which includes padding) and swap to URL-safe alphabet
        return Buffer.from(raw.toString('base64').replace(/\+/g, '-').replace(/\//g, '_'))
    }

    private decrypt(token: Uint8Array): Uint8Array {
        // Python's Fernet stores tokens as base64url-encoded bytes
        const buf = Buffer.from(Buffer.from(token).toString(), 'base64url')
        if (buf.length < FERNET_HEADER_SIZE + HMAC_SIZE) {
            throw new Error('Fernet token too short')
        }
        if (buf[0] !== FERNET_VERSION) {
            throw new Error(`Unexpected Fernet version: ${buf[0]}`)
        }

        const body = buf.subarray(0, buf.length - HMAC_SIZE)
        const providedHmac = buf.subarray(buf.length - HMAC_SIZE)
        let decryptError: Error | undefined

        for (const key of [this.primaryKey, ...this.fallbackKeys]) {
            const computedHmac = crypto.createHmac('sha256', key.signingKey).update(body).digest()

            if (!crypto.timingSafeEqual(providedHmac, computedHmac)) {
                continue
            }

            const iv = buf.subarray(9, 25)
            const ciphertext = buf.subarray(FERNET_HEADER_SIZE, buf.length - HMAC_SIZE)

            try {
                const decipher = crypto.createDecipheriv('aes-128-cbc', key.encryptionKey, iv)
                return Buffer.concat([decipher.update(ciphertext), decipher.final()])
            } catch (error) {
                decryptError = error instanceof Error ? error : new Error(String(error))
            }
        }

        throw decryptError ?? new Error('Fernet HMAC verification failed')
    }
}
