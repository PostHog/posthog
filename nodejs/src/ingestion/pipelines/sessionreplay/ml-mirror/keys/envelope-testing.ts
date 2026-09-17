import { createDecipheriv } from 'node:crypto'
import { isDeepStrictEqual } from 'node:util'

import { MlDataKey, MlEncryptedEnvelope, TAG_BYTES, canonicalJson } from './crypto'
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

export const TrainingEncryptionVector = { ...vector, envelope: vector.envelope as MlEncryptedEnvelope }
