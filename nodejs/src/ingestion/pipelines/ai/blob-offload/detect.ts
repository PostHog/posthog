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
    belowFloorCount: number
    belowFloorBytes: number
}

const DATA_URI = /^data:([\w.+-]+\/[\w.+-]+);base64,([A-Za-z0-9+/=\s]+)$/
const MIME = /^[\w.+-]+\/[\w.+-]+$/
// Canonical base64 only (no whitespace, padding only terminal, length % 4 === 0): provider
// `data` fields are never wrapped, and Buffer.from decodes leniently enough that a looser
// match would silently corrupt long plain text that happens to fit the charset.
const CANONICAL_BASE64 = /^[A-Za-z0-9+/]+={0,2}$/

interface Extraction {
    blobsByHash: Map<string, DetectedBlob>
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
    return pointerFor(state, match[2], match[1], 'data_uri') ?? value
}

function isBase64String(value: unknown): value is string {
    return typeof value === 'string' && value.length % 4 === 0 && CANONICAL_BASE64.test(value)
}

/** Shape detectors for providers that carry raw base64 with the mime in a sibling field. */
function extractFromObject(
    state: Extraction,
    obj: Record<string, unknown>,
    parentKey: string | null
): Record<string, unknown> {
    if (
        obj.type === 'base64' &&
        typeof obj.media_type === 'string' &&
        MIME.test(obj.media_type) &&
        isBase64String(obj.data)
    ) {
        const pointer = pointerFor(state, obj.data, obj.media_type, 'anthropic_source')
        if (pointer) {
            return { ...obj, data: pointer }
        }
    }
    const geminiMime =
        typeof obj.mimeType === 'string' ? obj.mimeType : typeof obj.mime_type === 'string' ? obj.mime_type : null
    if (geminiMime && MIME.test(geminiMime) && isBase64String(obj.data)) {
        const pointer = pointerFor(state, obj.data, geminiMime, 'gemini_inline_data')
        if (pointer) {
            return { ...obj, data: pointer }
        }
    }
    if (parentKey === 'input_audio' && typeof obj.format === 'string' && isBase64String(obj.data)) {
        const pointer = pointerFor(state, obj.data, `audio/${obj.format}`, 'openai_input_audio')
        if (pointer) {
            return { ...obj, data: pointer }
        }
    }
    let changed = false
    const rewritten: Record<string, unknown> = {}
    for (const [key, child] of Object.entries(obj)) {
        const newChild = extractFromNode(state, child, key)
        rewritten[key] = newChild
        if (newChild !== child) {
            changed = true
        }
    }
    return changed ? rewritten : obj
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
        belowFloorCount: 0,
        belowFloorBytes: 0,
        minBase64Length: opts.minBase64Length,
    }
    const rewritten = extractFromNode(state, value, null)
    return {
        value: rewritten,
        blobs: [...state.blobsByHash.values()],
        belowFloorCount: state.belowFloorCount,
        belowFloorBytes: state.belowFloorBytes,
    }
}
