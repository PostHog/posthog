import { gunzipSync, strFromU8, strToU8 } from 'fflate'
import { Decompress as ZstdDecompress } from 'fzstd'
import { EventType, IncrementalSource } from 'posthog-js/rrweb-types'

import { ReplayTelemetry } from '../telemetry'
import { throttleCapture } from './throttle-capturing'

interface CompressedEventWithTime {
    cv: string
    type: number
    data: any
    timestamp: number
}

function isCompressedEvent(ev: unknown): ev is CompressedEventWithTime {
    return typeof ev === 'object' && ev !== null && 'cv' in ev
}

// A single compressed field never comes near this. It stops a crafted payload from exhausting the tab.
export const MAX_EXPANDED_FIELD_BYTES = 256 * 1024 * 1024

/** A cap on the bytes that every compressed field of one source may expand to, shared across fields. */
export class ExpansionBudget {
    constructor(public remaining: number) {}

    take(bytes: number): void {
        if (bytes > this.remaining) {
            throw new ExpansionBudgetExceededError()
        }
        this.remaining -= bytes
    }
}

/** Thrown when a source's compressed fields would expand past its budget. Parsing stops instead of skipping the field. */
export class ExpansionBudgetExceededError extends Error {
    constructor() {
        super('The recording expands to more data than can be played back')
    }
}

const readLittleEndian = (bytes: Uint8Array, offset: number, length: number): number => {
    let value = 0
    for (let i = length - 1; i >= 0; i--) {
        value = value * 256 + bytes[offset + i]
    }
    return value
}

// Where the first zstd frame ends: past its header, its blocks and its optional checksum.
function zstdFirstFrameEnd(raw: Uint8Array): number {
    const descriptor = raw[4]
    const singleSegment = (descriptor >> 5) & 1
    const sizeBytes = [singleSegment ? 1 : 0, 2, 4, 8][descriptor >> 6]
    let offset = 5 + (singleSegment ? 0 : 1) + [0, 1, 2, 4][descriptor & 3] + sizeBytes
    for (;;) {
        if (offset + 3 > raw.byteLength) {
            return Infinity
        }
        const blockHeader = readLittleEndian(raw, offset, 3)
        const blockType = (blockHeader >> 1) & 3
        // An RLE block stores one byte, whatever size it expands to.
        offset += 3 + (blockType === 1 ? 1 : blockHeader >> 3)
        if (blockHeader & 1) {
            break
        }
    }
    return offset + ((descriptor >> 2) & 1 ? 4 : 0)
}

// The content size and window size a zstd frame header declares. fzstd allocates the larger before decoding.
function zstdDeclaredSizes(raw: Uint8Array): { contentSize: number; windowSize: number } {
    const descriptor = raw[4]
    const singleSegment = (descriptor >> 5) & 1
    const sizeBytes = [singleSegment ? 1 : 0, 2, 4, 8][descriptor >> 6]
    let windowSize = 0
    if (!singleSegment) {
        const windowByte = raw[5]
        const windowBase = 2 ** (10 + (windowByte >> 3))
        windowSize = windowBase + (windowBase / 8) * (windowByte & 7)
    }
    const offset = 5 + (singleSegment ? 0 : 1) + [0, 1, 2, 4][descriptor & 3]
    const contentSize = sizeBytes ? readLittleEndian(raw, offset, sizeBytes) + (sizeBytes === 2 ? 256 : 0) : 0
    return { contentSize, windowSize: singleSegment ? contentSize : windowSize }
}

function zstdDecompressWithLimit(raw: Uint8Array, limit: number, overLimit: () => Error): Uint8Array {
    // fzstd allocates a window for every frame it meets, so only a single frame's header can be checked up front.
    if (zstdFirstFrameEnd(raw) !== raw.byteLength) {
        throw new Error('zstd payload is not a single frame')
    }
    const { contentSize, windowSize } = zstdDeclaredSizes(raw)
    // fzstd allocates the window before it decodes, so a crafted window must stay under the per-field cap.
    if (windowSize > MAX_EXPANDED_FIELD_BYTES) {
        throw new Error('zstd payload declares a window over the expanded size limit')
    }
    if (contentSize > limit) {
        throw overLimit()
    }
    // Streaming lets a frame that declares no size stop as soon as its output passes the limit.
    const chunks: Uint8Array[] = []
    let total = 0
    const stream = new ZstdDecompress((chunk) => {
        total += chunk.byteLength
        if (total > limit) {
            throw overLimit()
        }
        chunks.push(chunk)
    })
    stream.push(raw, true)
    const output = new Uint8Array(total)
    let offset = 0
    for (const chunk of chunks) {
        output.set(chunk, offset)
        offset += chunk.byteLength
    }
    return output
}

// dispatch to either gzip or zstd based on their standard magic bytes prefix
function decompressSync(raw: Uint8Array, budget?: ExpansionBudget): Uint8Array {
    const limit = Math.min(MAX_EXPANDED_FIELD_BYTES, budget?.remaining ?? Infinity)
    // Past the shared budget the whole source stops. Past the per-field limit only this field is skipped.
    const overLimit = (): Error =>
        limit < MAX_EXPANDED_FIELD_BYTES
            ? new ExpansionBudgetExceededError()
            : new Error('Compressed field declares more than the expanded size limit')
    if (raw[0] === 0x1f && raw[1] === 0x8b) {
        // fflate allocates exactly the size in the gzip trailer and never grows past it.
        if (readLittleEndian(raw, raw.byteLength - 4, 4) > limit) {
            throw overLimit()
        }
        const output = gunzipSync(raw)
        budget?.take(output.byteLength)
        return output
    }
    if (raw[0] === 0x28 && raw[1] === 0xb5 && raw[2] === 0x2f && raw[3] === 0xfd) {
        const output = zstdDecompressWithLimit(raw, limit, overLimit)
        budget?.take(output.byteLength)
        return output
    }
    throw new Error(
        `cv payload is neither gzip nor zstd (leading bytes ${Array.from(raw.slice(0, 4), (b) =>
            b.toString(16).padStart(2, '0')
        ).join(' ')})`
    )
}

function unzip(compressedStr: string | undefined, budget?: ExpansionBudget): any {
    if (!compressedStr) {
        return undefined
    }
    return JSON.parse(strFromU8(decompressSync(strToU8(compressedStr, true), budget)))
}

export function decompressEvent(
    ev: unknown,
    sessionRecordingId: string,
    telemetry: ReplayTelemetry,
    budget?: ExpansionBudget
): unknown {
    try {
        if (isCompressedEvent(ev)) {
            if (ev.cv === '2024-10') {
                if (ev.type === EventType.FullSnapshot && typeof ev.data === 'string') {
                    return {
                        ...ev,
                        data: unzip(ev.data, budget),
                    }
                } else if (
                    ev.type === EventType.IncrementalSnapshot &&
                    typeof ev.data === 'object' &&
                    'source' in ev.data
                ) {
                    if (ev.data.source === IncrementalSource.StyleSheetRule) {
                        return {
                            ...ev,
                            data: {
                                ...ev.data,
                                source: IncrementalSource.StyleSheetRule,
                                adds: unzip(ev.data.adds, budget),
                                removes: unzip(ev.data.removes, budget),
                            },
                        }
                    } else if (ev.data.source === IncrementalSource.Mutation && 'texts' in ev.data) {
                        return {
                            ...ev,
                            data: {
                                ...ev.data,
                                source: IncrementalSource.Mutation,
                                adds: unzip(ev.data.adds, budget),
                                removes: unzip(ev.data.removes, budget),
                                texts: unzip(ev.data.texts, budget),
                                attributes: unzip(ev.data.attributes, budget),
                            },
                        }
                    }
                }
            } else {
                throttleCapture(`${sessionRecordingId}-unknown-compressed-event-version`, () => {
                    telemetry.captureException(new Error('Unknown compressed event version'), {
                        feature: 'session-recording-compressed-event-decompression',
                        compressedEvent: ev,
                        compressionVersion: ev.cv,
                    })
                })
                return ev
            }
        }
        return ev
    } catch (e) {
        if (e instanceof ExpansionBudgetExceededError) {
            throw e
        }
        throttleCapture(`${sessionRecordingId}-unknown-compressed-event-version`, () => {
            telemetry.captureException((e as Error) || new Error('Could not decompress event'), {
                feature: 'session-recording-compressed-event-decompression',
                compressedEvent: ev,
            })
        })
        return ev
    }
}
