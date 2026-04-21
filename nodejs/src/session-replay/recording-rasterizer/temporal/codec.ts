import { PayloadCodec } from '@temporalio/common'
import { Payload as PayloadProto } from '@temporalio/common/lib/interfaces'
import { temporal } from '@temporalio/proto'
import * as crypto from 'crypto'

const ENCODING_KEY = 'encoding'
const ENCRYPTED_ENCODING = 'binary/encrypted'
const FERNET_VERSION = 0x80
const FERNET_HEADER_SIZE = 1 + 8 + 16 // version + timestamp + IV
const HMAC_SIZE = 32

/**
 * Fernet-compatible encryption codec that matches PostHog's Python EncryptionCodec.
 *
 * The Python side (posthog/temporal/common/codec.py) derives a Fernet key from
 * Django's SECRET_KEY: zero-pad to 32 bytes, base64url-encode. The first 16 bytes
 * of the decoded key are the HMAC-SHA256 signing key, the last 16 bytes are the
 * AES-128-CBC encryption key.
 */
export class EncryptionCodec implements PayloadCodec {
    private signingKey: Buffer
    private encryptionKey: Buffer

    constructor(secretKey: string) {
        // Match Python: pad with null bytes on the left, truncate to 32 bytes
        const padded = Buffer.alloc(32)
        const keyBytes = Buffer.from(secretKey, 'utf-8')
        if (keyBytes.length > 32) {
            console.warn(`EncryptionCodec: secret key is ${keyBytes.length} bytes, truncating to 32`)
        }
        const padLen = Math.max(32 - keyBytes.length, 0)
        keyBytes.copy(padded, padLen, 0, Math.min(keyBytes.length, 32))

        this.signingKey = padded.subarray(0, 16)
        this.encryptionKey = padded.subarray(16, 32)
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

        const cipher = crypto.createCipheriv('aes-128-cbc', this.encryptionKey, iv)
        const ciphertext = Buffer.concat([cipher.update(data), cipher.final()])

        // Fernet token: version || timestamp (big-endian 64-bit) || IV || ciphertext
        const body = Buffer.alloc(FERNET_HEADER_SIZE + ciphertext.length)
        body[0] = FERNET_VERSION
        body.writeBigUInt64BE(timestamp, 1)
        iv.copy(body, 9)
        ciphertext.copy(body, FERNET_HEADER_SIZE)

        const hmac = crypto.createHmac('sha256', this.signingKey).update(body).digest()
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
        const computedHmac = crypto.createHmac('sha256', this.signingKey).update(body).digest()

        if (!crypto.timingSafeEqual(providedHmac, computedHmac)) {
            throw new Error('Fernet HMAC verification failed')
        }

        const iv = buf.subarray(9, 25)
        const ciphertext = buf.subarray(FERNET_HEADER_SIZE, buf.length - HMAC_SIZE)

        const decipher = crypto.createDecipheriv('aes-128-cbc', this.encryptionKey, iv)
        return Buffer.concat([decipher.update(ciphertext), decipher.final()])
    }
}
