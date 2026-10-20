import { EventType, eventWithTime, fullSnapshotEvent, IncrementalSource } from 'posthog-js/rrweb-types'

import { transformEventToWeb } from '../mobile'
import { SCREEN_CHROME_PARENT_IDS, SCREENSHOT_ATTRIBUTE } from '../mobile/transformer/transformers'
import { noOpTelemetry, ReplayTelemetry } from '../telemetry'
import {
    EncodedRecordingSnapshot,
    RecordingSnapshot,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
} from '../types'
import { isObject } from '../utils'
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
    // Sources processed while viewport data was unavailable (meta patch failed). They are left out of
    // `snapshots` so a later pass — e.g. once events land — can re-process them with a viewport.
    viewportGaps?: Set<SourceKey>
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
        if (node && node.type === 2 && node.tagName === 'img' && node.attributes?.[SCREENSHOT_ATTRIBUTE]) {
            return node
        }
    }

    return undefined
}

function isLikelyMobileScreenshot(snapshot: RecordingSnapshot): boolean {
    return extractImgNodeFromMobileIncremental(snapshot) !== undefined
}

// An Android screenshot update transforms to a remove and an add of the same img and nothing else
function isScreenshotOnlyUpdate(snapshot: RecordingSnapshot): boolean {
    const data: any = (snapshot as any).data
    return (
        data.adds.length === 1 &&
        !data.texts?.length &&
        !data.attributes?.length &&
        (data.removes || []).every((removal: any) => removal.id === data.adds[0].node.id)
    )
}

// Flutter and iOS send every screenshot as a full snapshot. After transformEventToWeb its body holds the
// screenshot img and the empty keyboard, navigation bar and status bar containers; the synthetic Android
// full above holds only the img. Any other node, or one of those containers with content, means the frame
// is not just a screenshot.
function extractImgNodeFromScreenshotOnlyFull(fullSnapshot: fullSnapshotEvent): any | undefined {
    const htmlNode = (fullSnapshot.data.node as any).childNodes?.find(
        (node: any) => node.type === 2 && node.tagName === 'html'
    )
    const bodyNode = htmlNode?.childNodes?.find((node: any) => node.type === 2 && node.tagName === 'body')
    if (!bodyNode?.childNodes) {
        return undefined
    }

    let imgNode: any
    for (const child of bodyNode.childNodes) {
        if (child.attributes?.[SCREENSHOT_ATTRIBUTE]) {
            if (imgNode) {
                return undefined
            }
            imgNode = child
        } else if (!SCREEN_CHROME_PARENT_IDS.has(child.id) || child.childNodes?.length) {
            return undefined
        }
    }
    return imgNode
}

// rrweb keeps the img from the previous frame when only its src changes, so the same node id and
// size means the new screenshot can be swapped in place of it
function isSameScreenshot(previousImgNode: any | undefined, imgNode: any): boolean {
    return (
        !!previousImgNode &&
        previousImgNode.id === imgNode.id &&
        previousImgNode.attributes.width === imgNode.attributes.width &&
        previousImgNode.attributes.height === imgNode.attributes.height
    )
}

// Seeking replays from the nearest full snapshot, so a long run of src swaps keeps a real full snapshot
// every this many frames. Each one rebuilds the document, which is one WebKit flash per interval.
const SCREENSHOT_MUTATIONS_PER_FULL_SNAPSHOT = 30

function canSwapScreenshot(context: ProcessSnapshotContext, windowId: number, imgNode: any): boolean {
    return (
        isSameScreenshot(context.lastScreenshotByWindow[windowId], imgNode) &&
        (context.screenshotMutationsByWindow[windowId] ?? 0) < SCREENSHOT_MUTATIONS_PER_FULL_SNAPSHOT
    )
}

function rememberScreenshot(context: ProcessSnapshotContext, windowId: number, imgNode: any | undefined): void {
    context.lastScreenshotByWindow[windowId] = imgNode
    context.screenshotMutationsByWindow[windowId] = 0
}

function pushScreenshotMutation(
    context: ProcessSnapshotContext,
    windowId: number,
    timestamp: number,
    imgNode: any,
    currentTimestamp: number
): void {
    const mutation = createScreenshotMutation(windowId, timestamp, imgNode)
    context.result.push(mutation)
    context.sourceResult.push(mutation)
    context.previousTimestamp = currentTimestamp
    context.screenshotMutationsByWindow[windowId] = (context.screenshotMutationsByWindow[windowId] ?? 0) + 1
}

function createScreenshotMutation(windowId: number, timestamp: number, imgNode: any): RecordingSnapshot {
    const { src, width, height, style } = imgNode.attributes
    return {
        type: EventType.IncrementalSnapshot,
        timestamp,
        windowId,
        data: {
            source: IncrementalSource.Mutation,
            texts: [],
            attributes: [
                {
                    id: imgNode.id,
                    // rrweb ignores attribute values that are not strings
                    attributes: {
                        src,
                        width: String(width),
                        height: String(height),
                        style,
                        [SCREENSHOT_ATTRIBUTE]: 'true',
                    },
                },
            ],
            removes: [],
            adds: [],
        },
    } as RecordingSnapshot
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
    // No isEmptyObject early-return: a pass with no new input must still rebuild the full result from processingCache, or previously processed sources get wiped downstream.
    if (!sources || !snapshotsBySource) {
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
        sourceHadViewportGap: false,
        lastScreenshotByWindow: {},
        screenshotMutationsByWindow: {},
    }

    // Reset each pass: any source with a gap was left uncached, so it re-processes below and
    // re-registers its gap if the viewport is still unavailable.
    processingCache.viewportGaps = new Set<SourceKey>()

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
        context.sourceHadViewportGap = false
        const sortedSnapshots = sourceSnapshots.sort((a, b) => a.timestamp - b.timestamp)
        context.seenHashes = new Set<number>()
        // each source keeps a real full snapshot so seeking into it never depends on another source
        context.lastScreenshotByWindow = {}
        context.screenshotMutationsByWindow = {}
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

        if (context.sourceHadViewportGap) {
            // Don't freeze a meta-less result in the cache — a later pass (once viewport-defining
            // events load) must be able to re-process this source and patch the missing meta.
            processingCache.viewportGaps.add(sourceKey)
        } else {
            processingCache.snapshots[sourceKey] = context.sourceResult

            if (snapshotsBySource[sourceKey]) {
                snapshotsBySource[sourceKey].snapshots = []
            }
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
    // Set when a meta patch failed because no viewport was available for the current source
    sourceHadViewportGap: boolean
    // The screenshot img each window last rendered in this source. A same-size frame after it becomes an
    // attribute mutation of that img instead of a full snapshot, since rebuilding the document for every
    // frame flashes white in WebKit until the new img decodes.
    lastScreenshotByWindow: Record<number, any | undefined>
    // src swaps emitted since the window's last real full snapshot, capped at SCREENSHOT_MUTATIONS_PER_FULL_SNAPSHOT
    screenshotMutationsByWindow: Record<number, number>
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
        context.sourceHadViewportGap = true
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
        if (context.seenHashes.size === 0 && snapshotIndex > 0) {
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

    const windowId = snapshot.windowId
    const hasSeenFullForWindow = !!context.seenFullByWindow[windowId]

    if (snapshot.type === EventType.Meta) {
        context.hasSeenMeta = true
        rememberScreenshot(context, windowId, undefined)
    }

    if (snapshot.type === EventType.IncrementalSnapshot && isLikelyMobileScreenshot(snapshot)) {
        const imgNode = extractImgNodeFromMobileIncremental(snapshot)
        const screenshotOnly = isScreenshotOnlyUpdate(snapshot)

        if (screenshotOnly && canSwapScreenshot(context, windowId, imgNode)) {
            pushScreenshotMutation(context, windowId, snapshot.timestamp, imgNode, currentTimestamp)
            return
        }
        // an update that also changes something besides the screenshot can't be followed by a src swap
        rememberScreenshot(context, windowId, screenshotOnly ? imgNode : undefined)

        const syntheticTimestamp = Math.max(0, snapshot.timestamp - 1)
        const syntheticFull = createMinimalFullSnapshot(snapshot.windowId, syntheticTimestamp, imgNode)

        if (!hasSeenFullForWindow) {
            const metaInserted = pushPatchedMeta(syntheticTimestamp, snapshot.windowId, syntheticFull)
            context.hasSeenMeta = context.hasSeenMeta || metaInserted
            context.seenFullByWindow[windowId] = true
        }

        context.result.push(syntheticFull)
        context.sourceResult.push(syntheticFull)
    }

    // Anything else that changes the page, like the keyboard opening, isn't in the screenshot img, so the
    // next frame has to rebuild the document instead of only swapping the img src.
    if (
        snapshot.type === EventType.IncrementalSnapshot &&
        (snapshot.data as any)?.source === IncrementalSource.Mutation &&
        !isLikelyMobileScreenshot(snapshot)
    ) {
        rememberScreenshot(context, windowId, undefined)
    }

    // Like the FullSnapshot guard below: decompressEvent fails open, so a Mutation or StyleSheetRule
    // incremental whose compressed fields didn't decompress still carries strings where rrweb expects
    // arrays and would throw inside the Replayer at play time. Drop it rather than crash playback.
    if (snapshot.type === EventType.IncrementalSnapshot && isObject(snapshot.data)) {
        const data = snapshot.data as Record<string, unknown>
        const compressedFields =
            data.source === IncrementalSource.Mutation
                ? ['adds', 'removes', 'texts', 'attributes']
                : data.source === IncrementalSource.StyleSheetRule
                  ? ['adds', 'removes']
                  : []
        if (compressedFields.some((field) => typeof data[field] === 'string')) {
            throttleCapture(`${sessionRecordingId}-undecodable-incremental-snapshot`, () => {
                telemetry.captureException(new Error('Incremental snapshot could not be decoded'), {
                    sessionRecordingId,
                    sourceKey,
                    source: data.source,
                    feature: 'session-recording-incremental-snapshot-decoding',
                })
            })
            return
        }
    }

    if (snapshot.type === EventType.FullSnapshot) {
        const fullSnapshot = snapshot as RecordingSnapshot & fullSnapshotEvent & eventWithTime

        // A FullSnapshot whose payload failed to decompress (e.g. truncated at capture/ingestion) still
        // arrives here with `data` as the raw compressed string — decompressEvent swallows the gunzip error.
        // Dereferencing `data.node` below would throw, which processAllSnapshots surfaces as an unhandled
        // rejection that leaves every source stuck unpromoted and the player buffering forever. Drop it
        // instead: with no usable FullSnapshot the renderability machinery reports the recording unplayable.
        if (!isObject(fullSnapshot.data) || !isObject(fullSnapshot.data.node)) {
            throttleCapture(`${sessionRecordingId}-undecodable-full-snapshot`, () => {
                telemetry.captureException(new Error('Full snapshot could not be decoded'), {
                    sessionRecordingId,
                    sourceKey,
                    feature: 'session-recording-full-snapshot-decoding',
                })
            })
            return
        }

        const imgNode = extractImgNodeFromScreenshotOnlyFull(fullSnapshot)
        if (imgNode && canSwapScreenshot(context, windowId, imgNode)) {
            pushScreenshotMutation(context, windowId, snapshot.timestamp, imgNode, currentTimestamp)
            return
        }
        rememberScreenshot(context, windowId, imgNode)

        context.seenFullByWindow[snapshot.windowId] = true
        pushPatchedMeta(snapshot.timestamp, snapshot.windowId, snapshot)
        context.hasSeenMeta = false

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
