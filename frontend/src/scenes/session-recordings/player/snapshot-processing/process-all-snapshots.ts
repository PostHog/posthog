import posthog, { PostHog } from 'posthog-js'

import posthogEE from '@posthog/ee/exports'
import { EventType, eventWithTime, fullSnapshotEvent } from '@posthog/rrweb-types'

import { isEmptyObject, isObject } from 'lib/utils'
import {
    type DecompressionMode,
    getDecompressionWorkerManager,
} from 'scenes/session-recordings/player/snapshot-processing/DecompressionWorkerManager'
import {
    CHROME_EXTENSION_DENY_LIST,
    stripChromeExtensionDataFromNode,
} from 'scenes/session-recordings/player/snapshot-processing/chrome-extension-stripping'
import { chunkMutationSnapshot } from 'scenes/session-recordings/player/snapshot-processing/chunk-large-mutations'
import { decompressEvent } from 'scenes/session-recordings/player/snapshot-processing/decompress'
import {
    ViewportResolution,
    extractDimensionsFromMobileSnapshot,
} from 'scenes/session-recordings/player/snapshot-processing/patch-meta-event'
import { SourceKey, keyForSource } from 'scenes/session-recordings/player/snapshot-processing/source-key'
import { throttleCapture } from 'scenes/session-recordings/player/snapshot-processing/throttle-capturing'
import { yieldToMain } from 'scenes/session-recordings/player/snapshot-processing/yield-scheduler'

import {
    EncodedRecordingSnapshot,
    RecordingSnapshot,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
} from '~/types'

import { PostHogEE } from '../../../../../@posthog/ee/types'

export type ProcessingCache = Record<SourceKey, RecordingSnapshot[]>

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

function createMinimalFullSnapshot(windowId: string | undefined, timestamp: number, imgNode?: any): RecordingSnapshot {
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

/**
 * NB this mutates processingCache and returns the processed snapshots
 *
 * there are several steps to processing snapshots as received from the API
 * before they are playable, vanilla rrweb data
 */
export function processAllSnapshots(
    sources: SessionRecordingSnapshotSource[] | null,
    snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse> | null,
    processingCache: ProcessingCache,
    viewportForTimestamp: (timestamp: number) => ViewportResolution | undefined,
    sessionRecordingId: string,
    enableYielding?: false
): RecordingSnapshot[]
export function processAllSnapshots(
    sources: SessionRecordingSnapshotSource[] | null,
    snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse> | null,
    processingCache: ProcessingCache,
    viewportForTimestamp: (timestamp: number) => ViewportResolution | undefined,
    sessionRecordingId: string,
    enableYielding: true
): Promise<RecordingSnapshot[]>
export function processAllSnapshots(
    sources: SessionRecordingSnapshotSource[] | null,
    snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse> | null,
    processingCache: ProcessingCache,
    viewportForTimestamp: (timestamp: number) => ViewportResolution | undefined,
    sessionRecordingId: string,
    enableYielding: boolean = false
): RecordingSnapshot[] | Promise<RecordingSnapshot[]> {
    if (enableYielding) {
        return processAllSnapshotsAsync(
            sources,
            snapshotsBySource,
            processingCache,
            viewportForTimestamp,
            sessionRecordingId
        )
    }
    return processAllSnapshotsSync(
        sources,
        snapshotsBySource,
        processingCache,
        viewportForTimestamp,
        sessionRecordingId
    )
}

type ProcessSnapshotContext = {
    result: RecordingSnapshot[]
    sourceResult: RecordingSnapshot[]
    matchedExtensions: Set<string>
    hasSeenMeta: boolean
    seenFullByWindow: Record<string, boolean>
    previousTimestamp: number | null
    seenHashes: Set<number>
}

function createPushPatchedMeta(
    context: ProcessSnapshotContext,
    sourceKey: SourceKey,
    viewportForTimestamp: (timestamp: number) => ViewportResolution | undefined,
    sessionRecordingId: string
): (ts: number, winId?: string, fullSnapshot?: RecordingSnapshot) => boolean {
    return (ts: number, winId?: string, fullSnapshot?: RecordingSnapshot): boolean => {
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
                windowId: winId as unknown as string,
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
    pushPatchedMeta: (ts: number, winId?: string, fullSnapshot?: RecordingSnapshot) => boolean,
    sessionRecordingId: string,
    sourceKey: SourceKey
): 'continue' | 'process' {
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
            return 'continue'
        }
    } else {
        context.seenHashes = new Set<number>()
    }

    if (snapshot.type === EventType.Meta) {
        context.hasSeenMeta = true
    }

    const windowId = snapshot.windowId
    const hasSeenFullForWindow = !!context.seenFullByWindow[windowId]

    if (
        snapshot.type === EventType.IncrementalSnapshot &&
        !hasSeenFullForWindow &&
        isLikelyMobileScreenshot(snapshot)
    ) {
        const syntheticTimestamp = Math.max(0, snapshot.timestamp - 1)
        const imgNode = extractImgNodeFromMobileIncremental(snapshot)
        const syntheticFull = createMinimalFullSnapshot(snapshot.windowId, syntheticTimestamp, imgNode)
        const metaInserted = pushPatchedMeta(syntheticTimestamp, snapshot.windowId, syntheticFull)

        context.result.push(syntheticFull)
        context.sourceResult.push(syntheticFull)
        context.seenFullByWindow[windowId] = true
        context.hasSeenMeta = context.hasSeenMeta || metaInserted
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
    return 'process'
}

async function processAllSnapshotsAsync(
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

    const YIELD_BATCH_SIZE = 50

    for (let sourceIdx = 0; sourceIdx < sources.length; sourceIdx++) {
        const source = sources[sourceIdx]
        const sourceKey = keyForSource(source)

        if (sourceKey in processingCache) {
            for (const snapshot of processingCache[sourceKey]) {
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
            const action = processSnapshot(
                snapshot,
                sortedSnapshots,
                snapshotIndex,
                context,
                pushPatchedMeta,
                sessionRecordingId,
                sourceKey
            )

            if (action === 'continue') {
                continue
            }

            if (snapshotIndex % YIELD_BATCH_SIZE === 0 && snapshotIndex < sortedSnapshots.length - 1) {
                await yieldToMain()
            }
        }

        processingCache[sourceKey] = context.sourceResult

        if (sourceIdx < sources.length - 1) {
            await yieldToMain()
        }
    }

    context.result.sort((a, b) => a.timestamp - b.timestamp)
    return context.result
}

function processAllSnapshotsSync(
    sources: SessionRecordingSnapshotSource[] | null,
    snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse> | null,
    processingCache: ProcessingCache,
    viewportForTimestamp: (timestamp: number) => ViewportResolution | undefined,
    sessionRecordingId: string
): RecordingSnapshot[] {
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

    for (let sourceIdx = 0; sourceIdx < sources.length; sourceIdx++) {
        const source = sources[sourceIdx]
        const sourceKey = keyForSource(source)

        if (sourceKey in processingCache) {
            for (const snapshot of processingCache[sourceKey]) {
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
            const action = processSnapshot(
                snapshot,
                sortedSnapshots,
                snapshotIndex,
                context,
                pushPatchedMeta,
                sessionRecordingId,
                sourceKey
            )

            if (action === 'continue') {
                continue
            }
        }

        processingCache[sourceKey] = context.sourceResult
    }

    context.result.sort((a, b) => a.timestamp - b.timestamp)
    return context.result
}

let postHogEEModule: PostHogEE

function isRecordingSnapshot(x: unknown): x is RecordingSnapshot {
    return typeof x === 'object' && x !== null && 'type' in x && 'timestamp' in x
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

/**
 * We can receive data in one of multiple formats, so we treat it as unknown,
 * And if we can't process it, force it into eventWithTime
 *
 * If it can't be case as eventWithTime by this point, then it's probably not a valid event anyway
 */
function coerceToEventWithTime(d: unknown, sessionRecordingId: string): eventWithTime {
    // we decompress first so that we could support partial compression on mobile in the future
    const currentEvent = decompressEvent(d, sessionRecordingId)
    return postHogEEModule?.mobileReplay?.transformEventToWeb(currentEvent) ?? (currentEvent as eventWithTime)
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

const lengthPrefixedSnappyDecompress = async (
    uint8Data: Uint8Array,
    mode?: DecompressionMode,
    posthogInstance?: PostHog
): Promise<string> => {
    const workerManager = getDecompressionWorkerManager(mode, posthogInstance)
    const decompressedParts: string[] = []
    let offset = 0

    // Parse length-prefixed blocks: [4 bytes length][compressed block][4 bytes length][compressed block]...
    while (offset < uint8Data.byteLength) {
        // Read 4-byte length prefix (big-endian unsigned int)
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

        // Read compressed block
        if (offset + length > uint8Data.byteLength) {
            console.error(
                `Incomplete block at offset ${offset}, expected ${length} bytes, available ${uint8Data.byteLength - offset}`
            )
            break
        }

        const compressedBlock = uint8Data.subarray(offset, offset + length)
        offset += length

        const decompressedData = await workerManager.decompress(compressedBlock)

        // Convert bytes to string
        const textDecoder = new TextDecoder('utf-8')
        const decompressedText = textDecoder.decode(decompressedData)
        decompressedParts.push(decompressedText)
    }

    return decompressedParts.join('\n')
}

const rawSnappyDecompress = async (
    uint8Data: Uint8Array,
    mode?: DecompressionMode,
    posthogInstance?: PostHog
): Promise<string> => {
    const workerManager = getDecompressionWorkerManager(mode, posthogInstance)

    const decompressedData = await workerManager.decompress(uint8Data)

    const textDecoder = new TextDecoder('utf-8')
    return textDecoder.decode(decompressedData)
}

export const parseEncodedSnapshots = async (
    items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[] | ArrayBuffer | Uint8Array,
    sessionId: string,
    decompressionMode?: DecompressionMode,
    posthogInstance?: PostHog,
    enableYielding: boolean = false
): Promise<RecordingSnapshot[]> => {
    if (!postHogEEModule) {
        postHogEEModule = await posthogEE()
    }

    // Check if we received binary data (ArrayBuffer or Uint8Array)
    if (items instanceof ArrayBuffer || items instanceof Uint8Array) {
        const uint8Data = items instanceof Uint8Array ? items : new Uint8Array(items)

        if (isLengthPrefixedSnappy(uint8Data)) {
            try {
                const combinedText = await lengthPrefixedSnappyDecompress(uint8Data, decompressionMode, posthogInstance)

                const lines = combinedText.split('\n').filter((line) => line.trim().length > 0)
                return parseEncodedSnapshots(lines, sessionId, decompressionMode, posthogInstance, enableYielding)
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
            const combinedText = await rawSnappyDecompress(uint8Data, decompressionMode, posthogInstance)

            const lines = combinedText.split('\n').filter((line) => line.trim().length > 0)
            return parseEncodedSnapshots(lines, sessionId, decompressionMode, posthogInstance, enableYielding)
        } catch (error) {
            try {
                const textDecoder = new TextDecoder('utf-8')
                const combinedText = textDecoder.decode(uint8Data)

                const lines = combinedText.split('\n').filter((line) => line.trim().length > 0)
                return parseEncodedSnapshots(lines, sessionId, decompressionMode, posthogInstance, enableYielding)
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
    const PARSE_BATCH_SIZE = 100

    for (let i = 0; i < items.length; i++) {
        const l = items[i]
        if (!l) {
            // blob files have an empty line at the end
            continue
        }
        try {
            let snapshotLine: { windowId: string } | EncodedRecordingSnapshot
            if (typeof l === 'string') {
                // is loaded from blob v1 storage
                snapshotLine = JSON.parse(l) as EncodedRecordingSnapshot
                if (Array.isArray(snapshotLine)) {
                    snapshotLine = {
                        windowId: snapshotLine[0],
                        data: [snapshotLine[1]],
                    }
                }
            } else {
                // is loaded from file export
                snapshotLine = l
            }
            let snapshotData: ({ windowId: string } | EncodedRecordingSnapshot)[]
            if (isRecordingSnapshot(snapshotLine)) {
                // is loaded from file export
                snapshotData = [snapshotLine]
            } else {
                // is loaded from blob storage
                snapshotData = snapshotLine['data']
            }

            for (const d of snapshotData) {
                const snap = coerceToEventWithTime(d, sessionId)

                const baseSnapshot: RecordingSnapshot = {
                    windowId: snapshotLine['window_id'] || snapshotLine['windowId'],
                    ...snap,
                }

                // Apply chunking to the snapshot if needed
                const chunkedSnapshots = chunkMutationSnapshot(baseSnapshot)
                parsedLines.push(...chunkedSnapshots)
            }
        } catch {
            if (typeof l === 'string') {
                unparseableLines.push(l)
            }
        }

        if (enableYielding && (i + 1) % PARSE_BATCH_SIZE === 0 && i < items.length - 1) {
            await yieldToMain()
        }
    }

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
