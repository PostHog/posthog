import posthog, { PostHog } from 'posthog-js'

import { eventWithTime } from '@posthog/rrweb-types'

import { isObject } from 'lib/utils'
import { transformEventToWeb } from 'scenes/session-recordings/mobile-replay'
import { chunkMutationSnapshot } from 'scenes/session-recordings/player/snapshot-processing/chunk-large-mutations'
import { decompressEvent } from 'scenes/session-recordings/player/snapshot-processing/decompress'
import { getDecompressionWorkerManager } from 'scenes/session-recordings/player/snapshot-processing/DecompressionWorkerManager'
import { throttleCapture } from 'scenes/session-recordings/player/snapshot-processing/throttle-capturing'

import { EncodedRecordingSnapshot, RecordingSnapshot } from '~/types'

export type RegisterWindowIdCallback = (uuid: string) => number

export const createWindowIdRegistry = (): RegisterWindowIdCallback => {
    const uuidToIndex: Record<string, number> = {}
    return (uuid: string): number => {
        if (uuid in uuidToIndex) {
            return uuidToIndex[uuid]
        }
        const index = Object.keys(uuidToIndex).length + 1
        uuidToIndex[uuid] = index
        return index
    }
}

function isRecordingSnapshot(x: unknown): x is RecordingSnapshot {
    return (
        typeof x === 'object' &&
        x !== null &&
        'type' in x &&
        'timestamp' in x &&
        'windowId' in x &&
        typeof (x as RecordingSnapshot).windowId === 'number'
    )
}

const mobileFullSnapshot = (x: Record<string, any>): boolean => isObject(x.data) && 'wireframes' in x.data

const mobileIncrementalUpdate = (y: Record<string, any>): boolean => {
    return (
        'type' in y &&
        y.type === 3 &&
        isObject(y.data) &&
        'updates' in y.data &&
        Array.isArray(y.data.updates) &&
        y.data.updates.some((du) => isObject(du) && 'wireframe' in du)
    )
}

export function hasAnyWireframes(snapshotData: Record<string, any>[]): boolean {
    return snapshotData.some((d) => {
        return mobileFullSnapshot(d) || mobileIncrementalUpdate(d)
    })
}

function coerceToEventWithTime(d: unknown, sessionRecordingId: string): eventWithTime {
    const currentEvent = decompressEvent(d, sessionRecordingId)
    return transformEventToWeb(currentEvent) ?? (currentEvent as eventWithTime)
}

function isLengthPrefixedSnappy(uint8Data: Uint8Array): boolean {
    if (uint8Data.byteLength < 4) {
        return false
    }

    const firstLength = ((uint8Data[0] << 24) | (uint8Data[1] << 16) | (uint8Data[2] << 8) | uint8Data[3]) >>> 0

    if (firstLength === 0 || firstLength > uint8Data.byteLength) {
        return false
    }

    if (4 + firstLength > uint8Data.byteLength) {
        return false
    }

    return true
}

const lengthPrefixedSnappyDecompress = async (uint8Data: Uint8Array, posthogInstance?: PostHog): Promise<string> => {
    const workerManager = getDecompressionWorkerManager(posthogInstance)

    const compressedBlocks: Uint8Array[] = []
    let offset = 0

    while (offset < uint8Data.byteLength) {
        if (offset + 4 > uint8Data.byteLength) {
            console.error('Incomplete length prefix at offset', offset)
            break
        }

        const length =
            ((uint8Data[offset] << 24) |
                (uint8Data[offset + 1] << 16) |
                (uint8Data[offset + 2] << 8) |
                uint8Data[offset + 3]) >>>
            0
        offset += 4

        if (offset + length > uint8Data.byteLength) {
            console.error(
                `Incomplete block at offset ${offset}, expected ${length} bytes, available ${uint8Data.byteLength - offset}`
            )
            break
        }

        const compressedBlock = uint8Data.slice(offset, offset + length)
        compressedBlocks.push(compressedBlock)
        offset += length
    }

    const isParallel = compressedBlocks.length > 1
    const DECOMPRESSION_BATCH_SIZE = 10
    const decompressedBlocks: Uint8Array[] = []
    for (let i = 0; i < compressedBlocks.length; i += DECOMPRESSION_BATCH_SIZE) {
        const batch = compressedBlocks.slice(i, i + DECOMPRESSION_BATCH_SIZE)
        const results = await Promise.all(batch.map((block) => workerManager.decompress(block, { isParallel })))
        decompressedBlocks.push(...results)
        if (i + DECOMPRESSION_BATCH_SIZE < compressedBlocks.length) {
            await new Promise<void>((r) => setTimeout(r, 0))
        }
    }

    const textDecoder = new TextDecoder('utf-8')
    const decompressedParts = decompressedBlocks.map((data) => textDecoder.decode(data))

    return decompressedParts.join('\n')
}

const rawSnappyDecompress = async (uint8Data: Uint8Array, posthogInstance?: PostHog): Promise<string> => {
    const workerManager = getDecompressionWorkerManager(posthogInstance)

    const decompressedData = await workerManager.decompress(uint8Data, { isParallel: false })

    const textDecoder = new TextDecoder('utf-8')
    return textDecoder.decode(decompressedData)
}

function reportParseStats(
    posthogInstance: PostHog | undefined,
    snapshotCount: number,
    parseDuration: number,
    lineCount: number,
    compressionType: 'length_prefixed_snappy' | 'raw_snappy'
): void {
    if (!posthogInstance) {
        return
    }

    posthogInstance.capture('replay_parse_timing', {
        snapshot_count: snapshotCount,
        parse_duration_ms: parseDuration,
        line_count: lineCount,
        compression_type: compressionType,
    })
}

export const parseEncodedSnapshots = async (
    items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[] | ArrayBuffer | Uint8Array,
    sessionId: string,
    posthogInstance?: PostHog,
    registerWindowId?: RegisterWindowIdCallback
): Promise<RecordingSnapshot[]> => {
    const startTime = performance.now()

    const registerFn: RegisterWindowIdCallback = registerWindowId || createWindowIdRegistry()

    if (items instanceof ArrayBuffer || items instanceof Uint8Array) {
        const uint8Data = items instanceof Uint8Array ? items : new Uint8Array(items)

        if (isLengthPrefixedSnappy(uint8Data)) {
            try {
                const combinedText = await lengthPrefixedSnappyDecompress(uint8Data, posthogInstance)
                const lines = combinedText.split('\n').filter((line) => line.trim().length > 0)
                const snapshots = await parseEncodedSnapshots(lines, sessionId, posthogInstance, registerFn)
                const parseDuration = performance.now() - startTime
                reportParseStats(
                    posthogInstance,
                    snapshots.length,
                    parseDuration,
                    lines.length,
                    'length_prefixed_snappy'
                )
                return snapshots
            } catch (error) {
                console.error('Length-prefixed Snappy decompression failed:', error)
                posthog.captureException(new Error('Failed to decompress length-prefixed snapshot data'), {
                    sessionId,
                    error: error instanceof Error ? error.message : 'Unknown error',
                    feature: 'session-recording-client-side-decompression',
                })
                return []
            }
        }

        try {
            const combinedText = await rawSnappyDecompress(uint8Data, posthogInstance)
            const lines = combinedText.split('\n').filter((line) => line.trim().length > 0)
            const snapshots = await parseEncodedSnapshots(lines, sessionId, posthogInstance, registerFn)
            const parseDuration = performance.now() - startTime
            reportParseStats(posthogInstance, snapshots.length, parseDuration, lines.length, 'raw_snappy')
            return snapshots
        } catch (error) {
            try {
                const textDecoder = new TextDecoder('utf-8')
                const combinedText = textDecoder.decode(uint8Data)

                const lines = combinedText.split('\n').filter((line) => line.trim().length > 0)
                return parseEncodedSnapshots(lines, sessionId, posthogInstance, registerFn)
            } catch (decodeError) {
                console.error('Failed to decompress or decode binary data:', error, decodeError)
                posthog.captureException(new Error('Failed to process snapshot data'), {
                    sessionId,
                    decompressionError: error instanceof Error ? error.message : 'Unknown error',
                    decodeError: decodeError instanceof Error ? decodeError.message : 'Unknown error',
                    feature: 'session-recording-client-side-decompression',
                })
                return []
            }
        }
    }

    const lineCount = items.length
    const unparseableLines: string[] = []
    const parsedLines: RecordingSnapshot[] = []

    const parseItem = (l: RecordingSnapshot | EncodedRecordingSnapshot | string): void => {
        if (!l) {
            return
        }
        try {
            let snapshotLine:
                | { windowId?: string; window_id?: string; data?: unknown[] }
                | EncodedRecordingSnapshot
                | RecordingSnapshot
            if (typeof l === 'string') {
                snapshotLine = JSON.parse(l) as EncodedRecordingSnapshot

                if (Array.isArray(snapshotLine)) {
                    snapshotLine = {
                        windowId: snapshotLine[0],
                        data: [snapshotLine[1]],
                    }
                }
            } else {
                snapshotLine = l
            }

            if (isRecordingSnapshot(snapshotLine)) {
                const snap = coerceToEventWithTime(snapshotLine, sessionId)
                const baseSnapshot: RecordingSnapshot = {
                    windowId: snapshotLine.windowId,
                    ...snap,
                }
                const chunkedSnapshots = chunkMutationSnapshot(baseSnapshot)
                parsedLines.push(...chunkedSnapshots)
            } else if (
                'type' in snapshotLine &&
                'timestamp' in snapshotLine &&
                typeof snapshotLine['windowId'] === 'string'
            ) {
                const rawWindowId: string = snapshotLine['windowId']
                const windowId = registerFn(rawWindowId)
                const snap = coerceToEventWithTime(snapshotLine, sessionId)
                const baseSnapshot: RecordingSnapshot = {
                    windowId,
                    ...snap,
                }
                const chunkedSnapshots = chunkMutationSnapshot(baseSnapshot)
                parsedLines.push(...chunkedSnapshots)
            } else {
                const snapshotData = snapshotLine['data'] || []
                const rawWindowId: string = snapshotLine['window_id'] || snapshotLine['windowId'] || ''
                const windowId = registerFn(rawWindowId)

                for (const d of snapshotData) {
                    const snap = coerceToEventWithTime(d, sessionId)
                    const baseSnapshot: RecordingSnapshot = {
                        windowId,
                        ...snap,
                    }
                    const chunkedSnapshots = chunkMutationSnapshot(baseSnapshot)
                    parsedLines.push(...chunkedSnapshots)
                }
            }
        } catch {
            if (typeof l === 'string') {
                unparseableLines.push(l)
            }
        }
    }

    const reportUnparseableLines = (): void => {
        if (unparseableLines.length) {
            const extra = {
                playbackSessionId: sessionId,
                totalLineCount: lineCount,
                unparseableLinesCount: unparseableLines.length,
                exampleLines: unparseableLines.slice(0, 3),
            }
            throttleCapture(`${sessionId}-unparseable-lines`, () => {
                posthog.capture('session recording had unparseable lines', {
                    ...extra,
                    feature: 'session-recording-snapshot-processing',
                })
            })
        }
    }

    for (const item of items) {
        parseItem(item)
    }
    reportUnparseableLines()
    return parsedLines
}
