import { createDecipheriv } from 'node:crypto'
import { isDeepStrictEqual } from 'node:util'
import { brotliDecompressSync } from 'node:zlib'

import { parseJSON } from '~/common/utils/json-parse'

import { MlDataKey, MlEncryptedEnvelope, MlEnvelopeCodec, NONCE_BYTES, TAG_BYTES, canonicalJson } from './crypto'
import vector from './encryption-vector.json'

/** Nothing in production reads an envelope; tests use this to check what the encryptors write. */
export function decryptEnvelope(key: MlDataKey, envelope: MlEncryptedEnvelope, kind: string, ref?: string): Buffer {
    const context = { ...key.identity, kind, ...(ref ? { ref } : {}) }
    if (envelope.v !== 3 || !isDeepStrictEqual(envelope.context, context)) {
        throw new Error('ML envelope context mismatch')
    }
    const sealed = Buffer.from(envelope.ciphertext, 'base64')
    if (sealed.length < TAG_BYTES) {
        throw new Error('Invalid authenticated ML envelope')
    }
    const decipher = createDecipheriv('aes-256-gcm', key.plaintext, Buffer.from(envelope.nonce, 'base64'), {
        authTagLength: TAG_BYTES,
    })
    decipher.setAAD(Buffer.from(canonicalJson({ v: 3, context })))
    decipher.setAuthTag(sealed.subarray(sealed.length - TAG_BYTES))
    return Buffer.concat([decipher.update(sealed.subarray(0, sealed.length - TAG_BYTES)), decipher.final()])
}

const MAGIC = 'AISR03'
const HEADER_BYTES = MAGIC.length + 2

/** Takes the authenticated bytes from the frame rather than rebuilding them, so a canonical-JSON mismatch cannot fail a test for the wrong reason. */
export function decryptEnvelopeFrame(
    key: MlDataKey,
    frame: Buffer,
    kind: string,
    options: { ref?: string; codec: MlEnvelopeCodec }
): Buffer {
    if (frame.length < HEADER_BYTES || frame.subarray(0, MAGIC.length).toString() !== MAGIC) {
        throw new Error('Not an ML envelope frame')
    }
    // The magic and the length sit outside the authenticated data, so a frame must be bounded before it is sliced.
    const aadLength = frame.readUInt16BE(MAGIC.length)
    if (frame.length < HEADER_BYTES + aadLength + NONCE_BYTES + TAG_BYTES) {
        throw new Error('Invalid authenticated ML envelope')
    }
    const aad = frame.subarray(HEADER_BYTES, HEADER_BYTES + aadLength)
    const nonce = frame.subarray(HEADER_BYTES + aadLength, HEADER_BYTES + aadLength + NONCE_BYTES)
    const sealed = frame.subarray(HEADER_BYTES + aadLength + NONCE_BYTES)
    const context = { ...key.identity, kind, codec: options.codec, ...(options.ref ? { ref: options.ref } : {}) }
    if (!isDeepStrictEqual(parseJSON(aad.toString()), { v: 3, context })) {
        throw new Error('ML envelope context mismatch')
    }
    const decipher = createDecipheriv('aes-256-gcm', key.plaintext, nonce, { authTagLength: TAG_BYTES })
    decipher.setAAD(aad)
    decipher.setAuthTag(sealed.subarray(sealed.length - TAG_BYTES))
    const body = Buffer.concat([decipher.update(sealed.subarray(0, sealed.length - TAG_BYTES)), decipher.final()])
    return options.codec === 'brotli' ? brotliDecompressSync(body) : body
}

export const TrainingEncryptionVector = {
    ...vector,
    envelope: vector.envelope as MlEncryptedEnvelope,
    frame: { ...vector.frame, codec: vector.frame.codec as MlEnvelopeCodec },
}
