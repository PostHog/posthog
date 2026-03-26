import { EventType, eventWithTime, fullSnapshotEvent } from '@posthog/rrweb-types'

import { transformEventToWeb } from '../mobile'
import { noOpTelemetry, ReplayTelemetry } from '../telemetry'
import {
    EncodedRecordingSnapshot,
    RecordingSnapshot,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
} from '../types'
import { isEmptyObject, isObject } from '../utils'
import { CHROME_EXTENSION_DENY_LIST, stripChromeExtensionDataFromNode } from './chrome-extension-stripping'
import { chunkMutationSnapshot } from './chunk-large-mutations'
import { decompressEvent } from './decompress'
import { extractDimensionsFromMobileSnapshot, ViewportResolution } from './patch-meta-event'
import { keyForSource, SourceKey } from './source-key'
import { throttleCapture } from './throttle-capturing'

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
    const bodyChildNodes = imgNode ? [imgNode] : []

    const htmlNode = {
        type: 2,
        tagName: 'html',
        attributes: {
            'data-rrweb-id': 'minimal-html',
        },
        childNodes: [
            {
                type: 2,
                tagName: 'head',
                attributes: {
                    'data-rrweb-id': 'minimal-head',
                },
                childNodes: [],
            },
            {
                type: 2,
                tagName: 'body',
                attributes: {
                    'data-rrweb-id': 5,
                },
                childNodes: bodyChildNodes,
            },
        ],
    }
    const documentNode = {
        type: 0,
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
    sessionRecordingId: string,
    telemetry: ReplayTelemetry = noOpTelemetry
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
        const pushPatchedMeta = createPushPatchedMeta(
            context,
            sourceKey,
            viewportForTimestamp,
            sessionRecordingId,
            telemetry
        )

        for (let snapshotIndex = 0; snapshotIndex < sortedSnapshots.length; snapshotIndex++) {
            const snapshot = sortedSnapshots[snapshotIndex]
            processSnapshot(
                snapshot,
                sortedSnapshots,
                snapshotIndex,
                context,
                pushPatchedMeta,
                sessionRecordingId,
                sourceKey,
                telemetry
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
    sessionRecordingId: string,
    telemetry: ReplayTelemetry
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
                telemetry.capture('patched meta into web recording', {
                    throttleCaptureKey: `${sessionRecordingId}-patched-meta`,
                    sessionRecordingId,
                    sourceKey: sourceKey,
                    feature: 'session-recording-meta-patching',
                })
            })
            return true
        }
        throttleCapture(`${sessionRecordingId}-no-viewport-found`, () => {
            telemetry.captureException(new Error('No event viewport or meta snapshot found for full snapshot'), {
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
    sourceKey: SourceKey,
    telemetry: ReplayTelemetry
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
                telemetry.capture('session recording has duplicate snapshots', {
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
        y.data.updates.some((du: unknown) => isObject(du) && 'wireframe' in du)
    )
}

export function hasAnyWireframes(snapshotData: Record<string, any>[]): boolean {
    return snapshotData.some((d) => {
        return mobileFullSnapshot(d) || mobileIncrementalUpdate(d)
    })
}

function coerceToEventWithTime(d: unknown, sessionRecordingId: string, telemetry: ReplayTelemetry): eventWithTime {
    const currentEvent = decompressEvent(d, sessionRecordingId, telemetry)
    return transformEventToWeb(currentEvent, telemetry) ?? (currentEvent as eventWithTime)
}

export const parseJsonSnapshots = (
    items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[],
    sessionId: string,
    telemetry: ReplayTelemetry = noOpTelemetry,
    registerWindowId?: RegisterWindowIdCallback
): RecordingSnapshot[] => {
    const registerFn: RegisterWindowIdCallback = registerWindowId || createWindowIdRegistry()

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
                const snap = coerceToEventWithTime(snapshotLine, sessionId, telemetry)
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
                const snap = coerceToEventWithTime(snapshotLine, sessionId, telemetry)
                const baseSnapshot: RecordingSnapshot = {
                    windowId,
                    ...snap,
                }
                const chunkedSnapshots = chunkMutationSnapshot(baseSnapshot)
                parsedLines.push(...chunkedSnapshots)
            } else {
                const snapshotData = snapshotLine['data'] || []
                const rawWindowId =
                    'window_id' in snapshotLine ? snapshotLine['window_id'] || '' : snapshotLine['windowId'] || ''
                const windowId = registerFn(rawWindowId.toString())

                for (const d of snapshotData) {
                    const snap = coerceToEventWithTime(d, sessionId, telemetry)
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

    for (const item of items) {
        parseItem(item)
    }

    if (unparseableLines.length) {
        throttleCapture(`${sessionId}-unparseable-lines`, () => {
            telemetry.capture('session recording had unparseable lines', {
                playbackSessionId: sessionId,
                totalLineCount: items.length,
                unparseableLinesCount: unparseableLines.length,
                exampleLines: unparseableLines.slice(0, 3),
                feature: 'session-recording-snapshot-processing',
            })
        })
    }

    return parsedLines
}

function hashSnapshot(snapshot: RecordingSnapshot): number {
    const { delay, ...delayFreeSnapshot } = snapshot
    return cyrb53(JSON.stringify(delayFreeSnapshot))
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
