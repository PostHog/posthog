/** Decode/scrub/re-encode per-event `cv` compression (gzip stored as latin-1 codepoints). */
import { gunzipSync, gzipSync } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'

import { ScrubContext, ScrubTiming, isObject } from './config'
import { scrubFullSnapshot, scrubMutation } from './dom'

function latin1ToBytes(s: string): Buffer {
    const buf = Buffer.allocUnsafe(s.length)
    for (let i = 0; i < s.length; i++) {
        const cp = s.charCodeAt(i)
        if (cp > 0xff) {
            throw new Error(`codepoint U+${cp.toString(16)} > 0xFF in latin-1 gzip stream`)
        }
        buf[i] = cp
    }
    return buf
}

function decompressString(s: string, timing?: ScrubTiming): unknown {
    const start = performance.now()
    const json = gunzipSync(latin1ToBytes(s)).toString('utf8')
    const value = parseJSON(json)
    if (timing) {
        timing.decompressMs += performance.now() - start
    }
    return value
}

function compressToString(value: unknown, timing?: ScrubTiming): string {
    const start = performance.now()
    // latin1 is the inverse of latin1ToBytes; JSON.stringify escapes it on serialization.
    const out = gzipSync(Buffer.from(JSON.stringify(value), 'utf8')).toString('latin1')
    if (timing) {
        timing.recompressMs += performance.now() - start
    }
    return out
}

/** Scrub a `cv`-compressed FullSnapshot event in place. Returns whether it changed. */
export function scrubCompressedFullSnapshot(ctx: ScrubContext, event: Record<string, unknown>): boolean {
    const data = event.data
    if (typeof data !== 'string') {
        // Not actually whole-blob compressed — scrub as a plain object.
        return scrubFullSnapshot(ctx, data)
    }
    const payload = decompressString(data, ctx.timing)
    if (!scrubFullSnapshot(ctx, payload)) {
        return false
    }
    event.data = compressToString(payload, ctx.timing)
    return true
}

/** Scrub a `cv`-compressed Mutation event in place. Returns whether it changed. */
export function scrubCompressedMutation(ctx: ScrubContext, event: Record<string, unknown>): boolean {
    const data = event.data
    if (!isObject(data)) {
        return false
    }

    // Sub-fields are gzipped strings on the wire but may arrive as plain arrays; handle both.
    const texts = readSubfield(data.texts, ctx.timing)
    const attributes = readSubfield(data.attributes, ctx.timing)
    const adds = readSubfield(data.adds, ctx.timing)

    const synthetic: Record<string, unknown> = {
        source: data.source,
        texts: texts.array,
        attributes: attributes.array,
        adds: adds.array,
        // `removes` is ids-only and untouched — left as-is.
    }

    if (!scrubMutation(ctx, synthetic)) {
        return false
    }

    // Array sub-fields were mutated in place; only re-encode the ones that arrived gzipped.
    if (texts.wasCompressed) {
        data.texts = compressToString(synthetic.texts, ctx.timing)
    }
    if (attributes.wasCompressed) {
        data.attributes = compressToString(synthetic.attributes, ctx.timing)
    }
    if (adds.wasCompressed) {
        data.adds = compressToString(synthetic.adds, ctx.timing)
    }
    return true
}

function readSubfield(field: unknown, timing?: ScrubTiming): { array: unknown[]; wasCompressed: boolean } {
    if (field === undefined || field === null) {
        return { array: [], wasCompressed: false }
    }
    if (typeof field === 'string') {
        if (field.length === 0) {
            return { array: [], wasCompressed: false }
        }
        const payload = decompressString(field, timing)
        if (!Array.isArray(payload)) {
            // Fail closed: a decodable-but-non-array sub-field is malformed; dropping beats shipping a zeroed block.
            throw new Error('cv mutation sub-field did not decode to an array')
        }
        return { array: payload, wasCompressed: true }
    }
    if (Array.isArray(field)) {
        return { array: field, wasCompressed: false }
    }
    throw new Error('cv mutation sub-field is neither a gzipped string nor an array')
}
