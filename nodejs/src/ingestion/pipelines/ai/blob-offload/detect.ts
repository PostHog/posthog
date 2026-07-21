import { createHash } from 'crypto'

import { decodeCanonicalBase64, isCanonicalBase64 } from './base64'
import { encodeBlobPointer, isBlobPointer } from './pointer'

export type BlobDetector = 'data_uri' | 'anthropic_source' | 'gemini_inline_data' | 'openai_input_audio' | 'raw_base64'

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
// Length-capped (RFC 4288 gives each of type/subtype 127 chars): the mime flows into the
// S3 Content-Type header and the pointer URI, so an unbounded value is a poison pill.
const MIME = /^(?=.{1,255}$)[\w.+-]+\/[\w.+-]+$/

const RAW_BASE64_MIME = 'application/octet-stream'

interface Extraction {
    blobsByHash: Map<string, DetectedBlob>
    savedChars: number
    belowFloorCount: number
    belowFloorBytes: number
    minBase64Length: number
}

function pointerFor(
    state: Extraction,
    base64: string,
    rawMime: string,
    detector: BlobDetector,
    countBelowFloor: boolean
): string | null {
    // Mime types are case-insensitive per RFC; canonical lowercase at rest keeps the
    // read side's mime allowlist comparisons exact.
    const mime = rawMime.toLowerCase()
    if (base64.length < state.minBase64Length) {
        if (countBelowFloor && isCanonicalBase64(base64)) {
            state.belowFloorCount += 1
            state.belowFloorBytes += Math.floor((base64.length * 3) / 4)
        }
        return null
    }
    const bytes = decodeCanonicalBase64(base64)
    if (!bytes || bytes.length === 0) {
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
    if (value.startsWith('data:')) {
        const match = DATA_URI.exec(value)
        if (!match || !MIME.test(match[1])) {
            return value
        }
        const pointer = pointerFor(state, match[2].replace(/\s+/g, ''), match[1], 'data_uri', true)
        if (pointer) {
            state.savedChars += value.length - pointer.length
            return pointer
        }
        return value
    }
    // Blind path: byte-strict (no whitespace compaction) so the stored bytes
    // reconstruct the exact original string; sub-floor strings are not counted
    // below-floor (every short ID would pollute the metric).
    const pointer = pointerFor(state, value, RAW_BASE64_MIME, 'raw_base64', false)
    if (pointer) {
        state.savedChars += value.length - pointer.length
        return pointer
    }
    return value
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
        typeof obj.data === 'string'
    ) {
        return { data: obj.data, mime: obj.media_type, detector: 'anthropic_source' }
    }
    const geminiMime =
        typeof obj.mimeType === 'string' ? obj.mimeType : typeof obj.mime_type === 'string' ? obj.mime_type : null
    if (geminiMime && MIME.test(geminiMime) && typeof obj.data === 'string') {
        return { data: obj.data, mime: geminiMime, detector: 'gemini_inline_data' }
    }
    // The composed mime is validated as a whole: `format` is attacker-controlled and
    // flows into the S3 Content-Type header, where invalid characters crash the sender.
    if (
        parentKey === 'input_audio' &&
        typeof obj.format === 'string' &&
        MIME.test(`audio/${obj.format}`) &&
        typeof obj.data === 'string'
    ) {
        return { data: obj.data, mime: `audio/${obj.format}`, detector: 'openai_input_audio' }
    }
    return null
}

// Stack safety: recursing without a bound would throw RangeError on adversarially
// nested payloads, and unclassified errors crash the consumer after retries.
// Content nested deeper passes through untouched, like every other miss.
const MAX_DEPTH = 256

function extractFromObject(
    state: Extraction,
    obj: Record<string, unknown>,
    parentKey: string | null,
    depth: number
): Record<string, unknown> {
    let base = obj
    const match = providerBlob(obj, parentKey)
    if (match) {
        const pointer = pointerFor(state, match.data, match.mime, match.detector, true)
        if (pointer) {
            state.savedChars += match.data.length - pointer.length
            base = { ...obj, data: pointer }
        }
    }
    let changed = base !== obj
    const entries: [string, unknown][] = []
    for (const [key, child] of Object.entries(base)) {
        const newChild = extractFromNode(state, child, key, depth + 1)
        entries.push([key, newChild])
        if (newChild !== child) {
            changed = true
        }
    }
    // fromEntries defines own properties, so a JSON-parsed `__proto__` key survives the rewrite.
    return changed ? Object.fromEntries(entries) : obj
}

function extractFromNode(state: Extraction, node: unknown, parentKey: string | null, depth: number): unknown {
    if (typeof node === 'string') {
        return extractFromString(state, node)
    }
    if (depth >= MAX_DEPTH) {
        return node
    }
    if (Array.isArray(node)) {
        const rewritten = node.map((child) => extractFromNode(state, child, parentKey, depth + 1))
        return rewritten.some((child, i) => child !== node[i]) ? rewritten : node
    }
    if (node !== null && typeof node === 'object') {
        return extractFromObject(state, node as Record<string, unknown>, parentKey, depth)
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
    const rewritten = extractFromNode(state, value, null, 0)
    return {
        value: rewritten,
        blobs: [...state.blobsByHash.values()],
        savedChars: state.savedChars,
        belowFloorCount: state.belowFloorCount,
        belowFloorBytes: state.belowFloorBytes,
    }
}
