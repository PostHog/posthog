import { EventType, eventWithTime, fullSnapshotEvent } from '@posthog/rrweb-types'

import {
    CHROME_EXTENSION_DENY_LIST,
    stripChromeExtensionDataFromNode,
} from 'scenes/session-recordings/player/snapshot-processing/chrome-extension-stripping'
import {
    ViewportResolution,
    extractDimensionsFromMobileSnapshot,
} from 'scenes/session-recordings/player/snapshot-processing/patch-meta-event'

import { RecordingSnapshot } from '~/types'

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
        attributes: { 'data-rrweb-id': 'minimal-html' },
        childNodes: [
            { type: 2, tagName: 'head', attributes: { 'data-rrweb-id': 'minimal-head' }, childNodes: [] },
            { type: 2, tagName: 'body', attributes: { 'data-rrweb-id': 5 }, childNodes: bodyChildNodes },
        ],
    }
    const documentNode = { type: 0, childNodes: [htmlNode] }
    return {
        type: EventType.FullSnapshot,
        timestamp,
        windowId,
        data: { node: documentNode, initialOffset: { top: 0, left: 0 } },
    } as unknown as RecordingSnapshot
}

/**
 * cyrb53 hash - same as in process-all-snapshots.ts
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

/**
 * Process snapshots for a single source. Performs the same transformations
 * as processAllSnapshots but for one source at a time — dedup, chrome extension
 * stripping, mobile screenshot synthesis, and meta patching.
 */
export function processSourceSnapshots(
    rawSnapshots: RecordingSnapshot[],
    viewportForTimestamp: (timestamp: number) => ViewportResolution | undefined
): RecordingSnapshot[] {
    if (!rawSnapshots.length) {
        return []
    }

    const result: RecordingSnapshot[] = []
    const matchedExtensions = new Set<string>()
    let hasSeenMeta = false
    const seenFullByWindow: Record<number, boolean> = {}
    let previousTimestamp: number | null = null
    let seenHashes = new Set<number>()

    const sorted = rawSnapshots.slice().sort((a, b) => a.timestamp - b.timestamp)

    const pushPatchedMeta = (ts: number, winId?: number, fullSnapshot?: RecordingSnapshot): boolean => {
        if (hasSeenMeta) {
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
            result.push(metaEvent)
            return true
        }
        return false
    }

    for (let i = 0; i < sorted.length; i++) {
        const snapshot = sorted[i]
        const currentTimestamp = snapshot.timestamp

        // Dedup snapshots with the same timestamp
        if (currentTimestamp === previousTimestamp) {
            if (seenHashes.size === 0 && i > 0) {
                seenHashes.add(hashSnapshot(sorted[i - 1]))
            }
            const snapshotHash = hashSnapshot(snapshot)
            if (seenHashes.has(snapshotHash)) {
                continue
            }
            seenHashes.add(snapshotHash)
        } else {
            seenHashes = new Set<number>()
        }

        if (snapshot.type === EventType.Meta) {
            hasSeenMeta = true
        }

        const windowId = snapshot.windowId
        const hasSeenFullForWindow = !!seenFullByWindow[windowId]

        // Mobile screenshot → synthesize FullSnapshot
        if (snapshot.type === EventType.IncrementalSnapshot && isLikelyMobileScreenshot(snapshot)) {
            const syntheticTimestamp = Math.max(0, snapshot.timestamp - 1)
            const imgNode = extractImgNodeFromMobileIncremental(snapshot)
            const syntheticFull = createMinimalFullSnapshot(snapshot.windowId, syntheticTimestamp, imgNode)

            if (!hasSeenFullForWindow) {
                const metaInserted = pushPatchedMeta(syntheticTimestamp, snapshot.windowId, syntheticFull)
                hasSeenMeta = hasSeenMeta || metaInserted
                seenFullByWindow[windowId] = true
            }

            result.push(syntheticFull)
        }

        if (snapshot.type === EventType.FullSnapshot) {
            seenFullByWindow[snapshot.windowId] = true
            pushPatchedMeta(snapshot.timestamp, snapshot.windowId, snapshot)
            hasSeenMeta = false

            const fullSnapshot = snapshot as RecordingSnapshot & fullSnapshotEvent & eventWithTime

            if (
                stripChromeExtensionDataFromNode(
                    fullSnapshot.data.node,
                    Object.keys(CHROME_EXTENSION_DENY_LIST),
                    matchedExtensions
                )
            ) {
                result.unshift({
                    type: EventType.Custom,
                    data: {
                        tag: 'chrome-extension-stripped',
                        payload: { extensions: Array.from(matchedExtensions) },
                    },
                    timestamp: snapshot.timestamp,
                    windowId: snapshot.windowId,
                })
            }
        }

        result.push(snapshot)
        previousTimestamp = currentTimestamp
    }

    return result
}
