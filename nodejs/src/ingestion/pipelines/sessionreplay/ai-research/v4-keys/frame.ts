import { createCipheriv, randomBytes } from 'node:crypto'

import { canonicalJson } from './canonical-json'

/** The owner and kind of a v4 object. Field names are the ones the v3 frame uses, plus `keyMonth`. */
export interface V4FrameContext {
    teamId: number
    keyMonth: string
    sessionId?: string
    kind: string
    codec: 'none' | 'brotli' | 'zstd'
    ref?: string
}

const MAGIC = Buffer.from('AISR03')
const NONCE_BYTES = 12

/**
 * The v3 AISR03 frame with `"v": 4` in the authenticated data, so a v3 reader never opens a v4 object. The format is
 * in `products/ai_training/docs/replay-data.md`, section "v4 dataset".
 */
export function sealV4Frame(
    key: Buffer,
    context: V4FrameContext,
    body: Buffer,
    nonce = randomBytes(NONCE_BYTES)
): Buffer {
    const aad = Buffer.from(canonicalJson({ v: 4, context }))
    if (aad.length > 0xffff) {
        throw new Error('v4 frame context is too long to frame')
    }
    const cipher = createCipheriv('aes-256-gcm', key, nonce, { authTagLength: 16 })
    cipher.setAAD(aad)
    const sealed = Buffer.concat([cipher.update(body), cipher.final(), cipher.getAuthTag()])
    const length = Buffer.alloc(2)
    length.writeUInt16BE(aad.length)
    return Buffer.concat([MAGIC, length, aad, nonce, sealed])
}
