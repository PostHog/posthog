import { createHash } from 'crypto'

import { encodeBlobPointer, isBlobPointer } from './pointer'

export type BlobDetector = 'data_uri' | 'anthropic_source' | 'gemini_inline_data' | 'openai_input_audio'

export interface DetectedBlob {
    bytes: Buffer
    mime: string
    hash: string
    detector: BlobDetector
}

export interface ExtractionResult {
    value: unknown
    blobs: DetectedBlob[]
    /** Serialized chars removed by pointer rewrites, summed per occurrence (dedup'd blobs still count each site). */
    savedChars: number
    belowFloorCount: number
    belowFloorBytes: number
}

const DATA_URI = /^data:([\w.+-]+\/[\w.+-]+);base64,([A-Za-z0-9+/=\s]+)$/
const MIME = /^[\w.+-]+\/[\w.+-]+$/
// Canonical base64 only (padding only terminal, length % 4 === 0): Buffer.from decodes
// leniently (stops at the first mid-string `=`), so a looser check would silently replace
// a payload with a pointer to its truncated decode. Provider `data` fields must match
// as-is; data-URI bodies may wrap with whitespace and are compacted before the check.
const CANONICAL_BASE64 = /^[A-Za-z0-9+/]+={0,2}$/

interface Extraction {
    blobsByHash: Map<string, DetectedBlob>
    savedChars: number
    belowFloorCount: number
    belowFloorBytes: number
    minBase64Length: number
}

function pointerFor(state: Extraction, base64: string, mime: string, detector: BlobDetector): string | null {
    if (base64.length < state.minBase64Length) {
        state.belowFloorCount += 1
        state.belowFloorBytes += Math.floor((base64.length * 3) / 4)
        return null
    }
    const bytes = Buffer.from(base64, 'base64')
    if (bytes.length === 0) {
        return null
    }
    const hash = createHash('sha256').update(bytes).digest('hex')
    if (!state.blobsByHash.has(hash)) {
        state.blobsByHash.set(hash, { bytes, mime, hash, detector })
    }
    return encodeBlobPointer({ algo: 'sha256', hash, mime, size: bytes.length })
}

function extractFromString(state: Extraction, value: string): string {
    if (isBlobPointer(value)) {
        return value
    }
    const match = DATA_URI.exec(value)
    if (!match) {
        return value
    }
    const compact = match[2].replace(/\s+/g, '')
    if (!isBase64String(compact)) {
        return value
    }
    const pointer = pointerFor(state, compact, match[1], 'data_uri')
    if (pointer) {
        state.savedChars += value.length - pointer.length
        return pointer
    }
    return value
}

function isBase64String(value: unknown): value is string {
    return typeof value === 'string' && value.length % 4 === 0 && CANONICAL_BASE64.test(value)
}

interface ProviderBlob {
    data: string
    mime: string
    detector: BlobDetector
}

/** Shape detectors for providers that carry raw base64 with the mime in a sibling field. */
function providerBlob(obj: Record<string, unknown>, parentKey: string | null): ProviderBlob | null {
    if (
        obj.type === 'base64' &&
        typeof obj.media_type === 'string' &&
        MIME.test(obj.media_type) &&
        isBase64String(obj.data)
    ) {
        return { data: obj.data, mime: obj.media_type, detector: 'anthropic_source' }
    }
    const geminiMime =
        typeof obj.mimeType === 'string' ? obj.mimeType : typeof obj.mime_type === 'string' ? obj.mime_type : null
    if (geminiMime && MIME.test(geminiMime) && isBase64String(obj.data)) {
        return { data: obj.data, mime: geminiMime, detector: 'gemini_inline_data' }
    }
    // The composed mime is validated as a whole: `format` is attacker-controlled and
    // flows into the S3 Content-Type header, where invalid characters crash the sender.
    if (
        parentKey === 'input_audio' &&
        typeof obj.format === 'string' &&
        MIME.test(`audio/${obj.format}`) &&
        isBase64String(obj.data)
    ) {
        return { data: obj.data, mime: `audio/${obj.format}`, detector: 'openai_input_audio' }
    }
    return null
}

function extractFromObject(
    state: Extraction,
    obj: Record<string, unknown>,
    parentKey: string | null
): Record<string, unknown> {
    let base = obj
    const match = providerBlob(obj, parentKey)
    if (match) {
        const pointer = pointerFor(state, match.data, match.mime, match.detector)
        if (pointer) {
            state.savedChars += match.data.length - pointer.length
            base = { ...obj, data: pointer }
        }
    }
    let changed = base !== obj
    const entries: [string, unknown][] = []
    for (const [key, child] of Object.entries(base)) {
        const newChild = extractFromNode(state, child, key)
        entries.push([key, newChild])
        if (newChild !== child) {
            changed = true
        }
    }
    // fromEntries defines own properties, so a JSON-parsed `__proto__` key survives the rewrite.
    return changed ? Object.fromEntries(entries) : obj
}

function extractFromNode(state: Extraction, node: unknown, parentKey: string | null): unknown {
    if (typeof node === 'string') {
        return extractFromString(state, node)
    }
    if (Array.isArray(node)) {
        const rewritten = node.map((child) => extractFromNode(state, child, parentKey))
        return rewritten.some((child, i) => child !== node[i]) ? rewritten : node
    }
    if (node !== null && typeof node === 'object') {
        return extractFromObject(state, node as Record<string, unknown>, parentKey)
    }
    return node
}

export function extractBlobs(value: unknown, opts: { minBase64Length: number }): ExtractionResult {
    const state: Extraction = {
        blobsByHash: new Map(),
        savedChars: 0,
        belowFloorCount: 0,
        belowFloorBytes: 0,
        minBase64Length: opts.minBase64Length,
    }
    const rewritten = extractFromNode(state, value, null)
    return {
        value: rewritten,
        blobs: [...state.blobsByHash.values()],
        savedChars: state.savedChars,
        belowFloorCount: state.belowFloorCount,
        belowFloorBytes: state.belowFloorBytes,
    }
}
