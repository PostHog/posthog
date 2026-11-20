import { gunzipSync, strFromU8, strToU8 } from 'fflate'
import { decompress as zstdDecompressSync } from 'fzstd'
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

const readLittleEndian = (bytes: Uint8Array, offset: number, length: number): number => {
    let value = 0
    for (let i = length - 1; i >= 0; i--) {
        value = value * 256 + bytes[offset + i]
    }
    return value
}

// The content size a zstd frame header declares, or undefined when the frame does not declare one.
function zstdDeclaredSize(raw: Uint8Array): number | undefined {
    const descriptor = raw[4]
    const sizeFlag = descriptor >> 6
    const singleSegment = (descriptor >> 5) & 1
    const sizeBytes = [singleSegment ? 1 : 0, 2, 4, 8][sizeFlag]
    if (sizeBytes === 0) {
        return undefined
    }
    const offset = 5 + (singleSegment ? 0 : 1) + [0, 1, 2, 4][descriptor & 3]
    return readLittleEndian(raw, offset, sizeBytes) + (sizeBytes === 2 ? 256 : 0)
}

// dispatch to either gzip or zstd based on their standard magic bytes prefix
function decompressSync(raw: Uint8Array): Uint8Array {
    if (raw[0] === 0x1f && raw[1] === 0x8b) {
        // fflate allocates exactly the size in the gzip trailer and never grows past it.
        if (readLittleEndian(raw, raw.byteLength - 4, 4) > MAX_EXPANDED_FIELD_BYTES) {
            throw new Error('gzip payload declares more than the expanded size limit')
        }
        return gunzipSync(raw)
    }
    if (raw[0] === 0x28 && raw[1] === 0xb5 && raw[2] === 0x2f && raw[3] === 0xfd) {
        if ((zstdDeclaredSize(raw) ?? 0) > MAX_EXPANDED_FIELD_BYTES) {
            throw new Error('zstd payload declares more than the expanded size limit')
        }
        return zstdDecompressSync(raw)
    }
    throw new Error(
        `cv payload is neither gzip nor zstd (leading bytes ${Array.from(raw.slice(0, 4), (b) =>
            b.toString(16).padStart(2, '0')
        ).join(' ')})`
    )
}

function unzip(compressedStr: string | undefined): any {
    if (!compressedStr) {
        return undefined
    }
    return JSON.parse(strFromU8(decompressSync(strToU8(compressedStr, true))))
}

export function decompressEvent(ev: unknown, sessionRecordingId: string, telemetry: ReplayTelemetry): unknown {
    try {
        if (isCompressedEvent(ev)) {
            if (ev.cv === '2024-10') {
                if (ev.type === EventType.FullSnapshot && typeof ev.data === 'string') {
                    return {
                        ...ev,
                        data: unzip(ev.data),
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
                                adds: unzip(ev.data.adds),
                                removes: unzip(ev.data.removes),
                            },
                        }
                    } else if (ev.data.source === IncrementalSource.Mutation && 'texts' in ev.data) {
                        return {
                            ...ev,
                            data: {
                                ...ev.data,
                                source: IncrementalSource.Mutation,
                                adds: unzip(ev.data.adds),
                                removes: unzip(ev.data.removes),
                                texts: unzip(ev.data.texts),
                                attributes: unzip(ev.data.attributes),
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
        throttleCapture(`${sessionRecordingId}-unknown-compressed-event-version`, () => {
            telemetry.captureException((e as Error) || new Error('Could not decompress event'), {
                feature: 'session-recording-compressed-event-decompression',
                compressedEvent: ev,
            })
        })
        return ev
    }
}
