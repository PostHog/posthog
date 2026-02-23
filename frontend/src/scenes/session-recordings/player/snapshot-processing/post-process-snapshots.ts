import posthog from 'posthog-js'

import { EventType, eventWithTime, fullSnapshotEvent } from '@posthog/rrweb-types'

import {
    CHROME_EXTENSION_DENY_LIST,
    stripChromeExtensionDataFromNode,
} from 'scenes/session-recordings/player/snapshot-processing/chrome-extension-stripping'
import {
    ViewportResolution,
    extractDimensionsFromMobileSnapshot,
} from 'scenes/session-recordings/player/snapshot-processing/patch-meta-event'
import { throttleCapture } from 'scenes/session-recordings/player/snapshot-processing/throttle-capturing'

import { RecordingSnapshot } from '~/types'

const YIELD_AFTER_MS = 50

export interface PostProcessingState {
    seenFullByWindow: Record<number, boolean>
    hasSeenMeta: boolean
    matchedExtensions: Set<string>
}

export function createPostProcessingState(): PostProcessingState {
    return {
        seenFullByWindow: {},
        hasSeenMeta: false,
        matchedExtensions: new Set<string>(),
    }
}

/*
    cyrb53 (c) 2018 bryc (github.com/bryc)
    License: Public domain. Attribution appreciated.
    A fast and simple 53-bit string hash function with decent collision resistance.
    Largely inspired by MurmurHash2/3, but with a focus on speed/simplicity.
*/
function cyrb53(str: string, seed = 0): number {
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

function hashSnapshot(snapshot: RecordingSnapshot): number {
    const { delay, ...delayFreeSnapshot } = snapshot
    return cyrb53(JSON.stringify(delayFreeSnapshot))
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

type ProcessSnapshotContext = {
    result: RecordingSnapshot[]
    matchedExtensions: Set<string>
    hasSeenMeta: boolean
    seenFullByWindow: Record<number, boolean>
    previousTimestamp: number | null
    seenHashes: Set<number>
}

function createPushPatchedMeta(
    context: ProcessSnapshotContext,
    viewportForTimestamp: ((timestamp: number) => ViewportResolution | undefined) | undefined,
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

        if (!viewport && viewportForTimestamp) {
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
            throttleCapture(`${sessionRecordingId}-patched-meta`, () => {
                posthog.capture('patched meta into web recording', {
                    throttleCaptureKey: `${sessionRecordingId}-patched-meta`,
                    sessionRecordingId,
                    feature: 'session-recording-meta-patching',
                })
            })
            return true
        }
        throttleCapture(`${sessionRecordingId}-no-viewport-found`, () => {
            posthog.captureException(new Error('No event viewport or meta snapshot found for full snapshot'), {
                throttleCaptureKey: `${sessionRecordingId}-no-viewport-found`,
                sessionRecordingId,
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
    sessionRecordingId: string
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
    context.previousTimestamp = currentTimestamp
}

export async function postProcessSnapshots(
    sortedSnapshots: RecordingSnapshot[],
    state: PostProcessingState,
    sessionRecordingId: string,
    viewportForTimestamp?: (timestamp: number) => ViewportResolution | undefined
): Promise<RecordingSnapshot[]> {
    if (!sortedSnapshots.length) {
        return []
    }

    const context: ProcessSnapshotContext = {
        result: [],
        matchedExtensions: state.matchedExtensions,
        hasSeenMeta: state.hasSeenMeta,
        seenFullByWindow: state.seenFullByWindow,
        previousTimestamp: null,
        seenHashes: new Set<number>(),
    }

    const pushPatchedMeta = createPushPatchedMeta(context, viewportForTimestamp, sessionRecordingId)

    let lastYield = performance.now()

    for (let i = 0; i < sortedSnapshots.length; i++) {
        processSnapshot(sortedSnapshots[i], sortedSnapshots, i, context, pushPatchedMeta, sessionRecordingId)

        const now = performance.now()
        if (now - lastYield > YIELD_AFTER_MS) {
            await new Promise<void>((r) => setTimeout(r, 0))
            lastYield = performance.now()
        }
    }

    // Persist cross-source state back.
    // matchedExtensions is a Set shared by reference, so mutations accumulate
    // automatically — only primitive fields need explicit writeback.
    state.hasSeenMeta = context.hasSeenMeta
    state.seenFullByWindow = context.seenFullByWindow

    return context.result
}
