import posthog, { PostHog } from 'posthog-js'

import { EventType, eventWithTime, fullSnapshotEvent } from '@posthog/rrweb-types'

import { isEmptyObject, isObject } from 'lib/utils'
import {
    decompressSnappy,
    getDecompressionWorkerManager,
} from 'scenes/session-recordings/player/snapshot-processing/DecompressionWorkerManager'
import {
    CHROME_EXTENSION_DENY_LIST,
    stripChromeExtensionDataFromNode,
} from 'scenes/session-recordings/player/snapshot-processing/chrome-extension-stripping'
import {
    ViewportResolution,
    extractDimensionsFromMobileSnapshot,
} from 'scenes/session-recordings/player/snapshot-processing/patch-meta-event'
import { SourceKey, keyForSource } from 'scenes/session-recordings/player/snapshot-processing/source-key'
import { throttleCapture } from 'scenes/session-recordings/player/snapshot-processing/throttle-capturing'

import {
    EncodedRecordingSnapshot,
    RecordingSnapshot,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
} from '~/types'

import {
    type RegisterWindowIdCallback,
    createWindowIdRegistry,
    isLengthPrefixedSnappy,
    processSnapshotLine,
} from './snapshot-parsing-utils'
import { toEventWithTime } from './to-event-with-time'

export type { RegisterWindowIdCallback } from './snapshot-parsing-utils'
export { createWindowIdRegistry } from './snapshot-parsing-utils'

function coerceToEventWithTime(d: unknown, sessionId: string): eventWithTime {
    return toEventWithTime(d, (e, phase) => {
        throttleCapture(`${sessionId}-${phase}-error`, () => {
            posthog.captureException(e instanceof Error ? e : new Error(String(e)), {
                sessionId,
                feature:
                    phase === 'decompress' ? 'session-recording-decompression' : 'session-recording-mobile-transform',
            })
        })
    })
}

export type ProcessingCache = {
    snapshots: Record<SourceKey, RecordingSnapshot[]>
}

function extractImgNodeFromMobileIncremental(snapshot: RecordingSnapshot): any | undefined {
    if (snapshot.type !== EventType.IncrementalSnapshot) {
        return undefined
    }
    const data: any = (snapshot as any).data

    if (data?.source !== 0 || !Array.isArray(data.adds)) {
        return undefined
    }

    const checksLimit = Math.min(data.adds.length, 3)
    for (let i = 0; i < checksLimit; i++) {
        const node = data.adds[i]?.node
        if (
            node &&
            node.type === 2 &&
            node.tagName === 'img' &&
            node.attributes?.['data-rrweb-id'] &&
            node.attributes?.width &&
            node.attributes?.height
        ) {
            return node
        }
    }

    return undefined
}

function isLikelyMobileScreenshot(snapshot: RecordingSnapshot): boolean {
    return extractImgNodeFromMobileIncremental(snapshot) !== undefined
}

function createMinimalFullSnapshot(windowId: number | undefined, timestamp: number, imgNode?: any): RecordingSnapshot {
    // Create a minimal rrweb full document snapshot structure sufficient for playback
    // For mobile screenshots, include the img node in body so dimension extraction works
    const bodyChildNodes = imgNode ? [imgNode] : []

    const htmlNode = {
        type: 2, // Element node
        tagName: 'html',
        attributes: {
            'data-rrweb-id': 'minimal-html',
        },
        childNodes: [
            {
                type: 2, // Element node
                tagName: 'head',
                attributes: {
                    'data-rrweb-id': 'minimal-head',
                },
                childNodes: [],
            },
            {
                type: 2, // Element node
                tagName: 'body',
                attributes: {
                    'data-rrweb-id': 5, // Match mobile transformer body id
                },
                childNodes: bodyChildNodes,
            },
        ],
    }
    const documentNode = {
        type: 0, // NodeType.Document
        childNodes: [htmlNode],
    }
    return {
        type: EventType.FullSnapshot,
        timestamp,
        windowId,
        data: {
            node: documentNode,
            initialOffset: { top: 0, left: 0 },
        },
    } as unknown as RecordingSnapshot
}

export async function processAllSnapshots(
    sources: SessionRecordingSnapshotSource[] | null,
    snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse> | null,
    processingCache: ProcessingCache,
    viewportForTimestamp: (timestamp: number) => ViewportResolution | undefined,
    sessionRecordingId: string
): Promise<RecordingSnapshot[]> {
    if (!sources || !snapshotsBySource || isEmptyObject(snapshotsBySource)) {
        return []
    }

    const context: ProcessSnapshotContext = {
        result: [],
        sourceResult: [],
        matchedExtensions: new Set<string>(),
        hasSeenMeta: false,
        seenFullByWindow: {},
        previousTimestamp: null,
        seenHashes: new Set<number>(),
    }

    const YIELD_AFTER_MS = 50
    let lastYield = performance.now()

    for (let sourceIdx = 0; sourceIdx < sources.length; sourceIdx++) {
        const source = sources[sourceIdx]
        const sourceKey = keyForSource(source)

        if (sourceKey in processingCache.snapshots) {
            const cachedSnapshots = processingCache.snapshots[sourceKey]
            for (const snapshot of cachedSnapshots) {
                context.result.push(snapshot)
            }
            continue
        }

        if (!(sourceKey in snapshotsBySource)) {
            continue
        }

        const sourceSnapshots = snapshotsBySource[sourceKey].snapshots || []
        if (!sourceSnapshots.length) {
            continue
        }

        context.sourceResult = []
        const sortedSnapshots = sourceSnapshots.sort((a, b) => a.timestamp - b.timestamp)
        context.seenHashes = new Set<number>()
        const pushPatchedMeta = createPushPatchedMeta(context, sourceKey, viewportForTimestamp, sessionRecordingId)

        for (let snapshotIndex = 0; snapshotIndex < sortedSnapshots.length; snapshotIndex++) {
            const snapshot = sortedSnapshots[snapshotIndex]
            processSnapshot(
                snapshot,
                sortedSnapshots,
                snapshotIndex,
                context,
                pushPatchedMeta,
                sessionRecordingId,
                sourceKey
            )
            if (performance.now() - lastYield > YIELD_AFTER_MS) {
                await new Promise<void>((r) => setTimeout(r, 0))
                lastYield = performance.now()
            }
        }

        processingCache.snapshots[sourceKey] = context.sourceResult

        if (snapshotsBySource[sourceKey]) {
            snapshotsBySource[sourceKey].snapshots = []
        }
    }

    context.result.sort((a, b) => a.timestamp - b.timestamp)

    return context.result
}

type ProcessSnapshotContext = {
    result: RecordingSnapshot[]
    sourceResult: RecordingSnapshot[]
    matchedExtensions: Set<string>
    hasSeenMeta: boolean
    seenFullByWindow: Record<number, boolean>
    previousTimestamp: number | null
    seenHashes: Set<number>
}

function createPushPatchedMeta(
    context: ProcessSnapshotContext,
    sourceKey: SourceKey,
    viewportForTimestamp: (timestamp: number) => ViewportResolution | undefined,
    sessionRecordingId: string
): (ts: number, winId?: number, fullSnapshot?: RecordingSnapshot) => boolean {
    return (ts: number, winId?: number, fullSnapshot?: RecordingSnapshot): boolean => {
        if (context.hasSeenMeta) {
            return false
        }

        let viewport: ViewportResolution | undefined
        if (fullSnapshot) {
            viewport = extractDimensionsFromMobileSnapshot(fullSnapshot)
        }

        if (!viewport) {
            viewport = viewportForTimestamp(ts)
        }

        if (viewport && viewport.width && viewport.height) {
            const metaEvent: RecordingSnapshot = {
                type: EventType.Meta,
                timestamp: ts,
                windowId: winId as number,
                data: {
                    width: parseInt(viewport.width, 10),
                    height: parseInt(viewport.height, 10),
                    href: viewport.href || 'unknown',
                },
            }
            context.result.push(metaEvent)
            context.sourceResult.push(metaEvent)
            throttleCapture(`${sessionRecordingId}-patched-meta`, () => {
                posthog.capture('patched meta into web recording', {
                    throttleCaptureKey: `${sessionRecordingId}-patched-meta`,
                    sessionRecordingId,
                    sourceKey: sourceKey,
                    feature: 'session-recording-meta-patching',
                })
            })
            return true
        }
        throttleCapture(`${sessionRecordingId}-no-viewport-found`, () => {
            posthog.captureException(new Error('No event viewport or meta snapshot found for full snapshot'), {
                throttleCaptureKey: `${sessionRecordingId}-no-viewport-found`,
                sessionRecordingId,
                sourceKey: sourceKey,
                feature: 'session-recording-meta-patching',
            })
        })
        return false
    }
}

function processSnapshot(
    snapshot: RecordingSnapshot,
    sortedSnapshots: RecordingSnapshot[],
    snapshotIndex: number,
    context: ProcessSnapshotContext,
    pushPatchedMeta: (ts: number, winId?: number, fullSnapshot?: RecordingSnapshot) => boolean,
    sessionRecordingId: string,
    sourceKey: SourceKey
): void {
    const currentTimestamp = snapshot.timestamp

    if (currentTimestamp === context.previousTimestamp) {
        if (context.seenHashes.size === 0) {
            context.seenHashes.add(hashSnapshot(sortedSnapshots[snapshotIndex - 1]))
        }
        const snapshotHash = hashSnapshot(snapshot)
        if (!context.seenHashes.has(snapshotHash)) {
            context.seenHashes.add(snapshotHash)
        } else {
            throttleCapture(`${sessionRecordingId}-duplicate-snapshot`, () => {
                posthog.capture('session recording has duplicate snapshots', {
                    sessionRecordingId,
                    sourceKey: sourceKey,
                })
            })
            return
        }
    } else {
        context.seenHashes = new Set<number>()
    }

    if (snapshot.type === EventType.Meta) {
        context.hasSeenMeta = true
    }

    const windowId = snapshot.windowId
    const hasSeenFullForWindow = !!context.seenFullByWindow[windowId]

    if (snapshot.type === EventType.IncrementalSnapshot && isLikelyMobileScreenshot(snapshot)) {
        const syntheticTimestamp = Math.max(0, snapshot.timestamp - 1)
        const imgNode = extractImgNodeFromMobileIncremental(snapshot)
        const syntheticFull = createMinimalFullSnapshot(snapshot.windowId, syntheticTimestamp, imgNode)

        // Only patch meta if we haven't seen a full snapshot for this window yet
        if (!hasSeenFullForWindow) {
            const metaInserted = pushPatchedMeta(syntheticTimestamp, snapshot.windowId, syntheticFull)
            context.hasSeenMeta = context.hasSeenMeta || metaInserted
            context.seenFullByWindow[windowId] = true
        }

        context.result.push(syntheticFull)
        context.sourceResult.push(syntheticFull)
    }

    if (snapshot.type === EventType.FullSnapshot) {
        context.seenFullByWindow[snapshot.windowId] = true
        pushPatchedMeta(snapshot.timestamp, snapshot.windowId, snapshot)
        context.hasSeenMeta = false

        const fullSnapshot = snapshot as RecordingSnapshot & fullSnapshotEvent & eventWithTime

        if (
            stripChromeExtensionDataFromNode(
                fullSnapshot.data.node,
                Object.keys(CHROME_EXTENSION_DENY_LIST),
                context.matchedExtensions
            )
        ) {
            context.result.unshift({
                type: EventType.Custom,
                data: {
                    tag: 'chrome-extension-stripped',
                    payload: {
                        extensions: Array.from(context.matchedExtensions),
                    },
                },
                timestamp: snapshot.timestamp,
                windowId: snapshot.windowId,
            })
        }
    }

    context.result.push(snapshot)
    context.sourceResult.push(snapshot)
    context.previousTimestamp = currentTimestamp
}

const mobileFullSnapshot = (x: Record<string, any>): boolean => isObject(x.data) && 'wireframes' in x.data

// the mobileFullSnapshot above wasn't catching recordings from React Native SDK 4.1.0 that were missing meta events so...
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

function hashSnapshot(snapshot: RecordingSnapshot): number {
    const { delay, ...delayFreeSnapshot } = snapshot
    return cyrb53(JSON.stringify(delayFreeSnapshot))
}

const lengthPrefixedSnappyDecompress = async (uint8Data: Uint8Array): Promise<string> => {
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

    const DECOMPRESSION_BATCH_SIZE = 10
    const decompressedBlocks: Uint8Array[] = []
    for (let i = 0; i < compressedBlocks.length; i += DECOMPRESSION_BATCH_SIZE) {
        const batch = compressedBlocks.slice(i, i + DECOMPRESSION_BATCH_SIZE)
        const results = await Promise.all(batch.map((block) => decompressSnappy(block)))
        decompressedBlocks.push(...results)
        if (i + DECOMPRESSION_BATCH_SIZE < compressedBlocks.length) {
            await new Promise<void>((r) => setTimeout(r, 0))
        }
    }

    const textDecoder = new TextDecoder('utf-8')
    const decompressedParts = decompressedBlocks.map((data) => textDecoder.decode(data))

    return decompressedParts.join('\n')
}

const rawSnappyDecompress = async (uint8Data: Uint8Array): Promise<string> => {
    const decompressedData = await decompressSnappy(uint8Data)

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

const parseEncodedSnapshotsBinaryMainThread = async (
    uint8Data: Uint8Array,
    sessionId: string,
    startTime: number,
    posthogInstance: PostHog | undefined,
    registerFn: RegisterWindowIdCallback
): Promise<RecordingSnapshot[]> => {
    if (isLengthPrefixedSnappy(uint8Data)) {
        try {
            const combinedText = await lengthPrefixedSnappyDecompress(uint8Data)
            const lines = combinedText.split('\n').filter((line) => line.trim().length > 0)
            const snapshots = await parseEncodedSnapshots(lines, sessionId, posthogInstance, registerFn)
            const parseDuration = performance.now() - startTime
            reportParseStats(posthogInstance, snapshots.length, parseDuration, lines.length, 'length_prefixed_snappy')
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
        const combinedText = await rawSnappyDecompress(uint8Data)
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

export const parseEncodedSnapshots = async (
    items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[] | ArrayBuffer | Uint8Array,
    sessionId: string,
    posthogInstance?: PostHog,
    registerWindowId?: RegisterWindowIdCallback
): Promise<RecordingSnapshot[]> => {
    const startTime = performance.now()

    const registerFn: RegisterWindowIdCallback = registerWindowId || createWindowIdRegistry()

    // Check if we received binary data (ArrayBuffer or Uint8Array)
    if (items instanceof ArrayBuffer || items instanceof Uint8Array) {
        const uint8Data = items instanceof Uint8Array ? items : new Uint8Array(items)

        const useWorker = posthogInstance?.getFeatureFlag('replay-snapshot-processing-worker') === 'test'
        if (useWorker) {
            const workerManager = getDecompressionWorkerManager(posthogInstance)
            if (workerManager?.snapshotWorkerAvailable) {
                try {
                    const result = await workerManager.processSnapshots(uint8Data, sessionId)
                    for (const mapping of result.windowIdMappings) {
                        registerFn(mapping.uuid)
                    }
                    if (result.metrics && posthogInstance) {
                        reportParseStats(
                            posthogInstance,
                            result.metrics.snapshotCount,
                            result.metrics.parseDurationMs,
                            result.metrics.lineCount,
                            result.metrics.compressionType as 'length_prefixed_snappy' | 'raw_snappy'
                        )
                    }
                    return result.snapshots
                } catch (error) {
                    console.warn(
                        '[parseEncodedSnapshots] Snapshot processing worker failed, falling back to main thread:',
                        error
                    )
                    if (posthogInstance) {
                        posthogInstance.capture('replay_snapshot_worker_processing_failed', {
                            error: error instanceof Error ? error.message : 'Unknown error',
                            sessionId,
                        })
                    }
                }
            }
        }

        return parseEncodedSnapshotsBinaryMainThread(uint8Data, sessionId, startTime, posthogInstance, registerFn)
    }

    const lineCount = items.length
    const unparseableLines: string[] = []
    const parsedLines: RecordingSnapshot[] = []

    const parseItem = (l: RecordingSnapshot | EncodedRecordingSnapshot | string): void => {
        if (!l) {
            return
        }
        try {
            const parsed = typeof l === 'string' ? (JSON.parse(l) as unknown) : l
            parsedLines.push(...processSnapshotLine(parsed, sessionId, registerFn, coerceToEventWithTime))
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

/*
    cyrb53 (c) 2018 bryc (github.com/bryc)
    License: Public domain. Attribution appreciated.
    A fast and simple 53-bit string hash function with decent collision resistance.
    Largely inspired by MurmurHash2/3, but with a focus on speed/simplicity.
*/
const cyrb53 = function (str: string, seed = 0): number {
    let h1 = 0xdeadbeef ^ seed,
        h2 = 0x41c6ce57 ^ seed
    for (let i = 0, ch; i < str.length; i++) {
        ch = str.charCodeAt(i)
        h1 = Math.imul(h1 ^ ch, 2654435761)
        h2 = Math.imul(h2 ^ ch, 1597334677)
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507)
    h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909)
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507)
    h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909)
    return 4294967296 * (2097151 & h2) + (h1 >>> 0)
}
