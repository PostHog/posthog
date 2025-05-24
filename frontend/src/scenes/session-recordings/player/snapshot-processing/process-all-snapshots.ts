import posthogEE from '@posthog/ee/exports'
import { EventType, eventWithTime, fullSnapshotEvent, IncrementalSource } from '@posthog/rrweb-types'
import { isObject } from 'lib/utils'
import posthog from 'posthog-js'
import {
    CHROME_EXTENSION_DENY_LIST,
    stripChromeExtensionDataFromNode,
} from 'scenes/session-recordings/player/snapshot-processing/chrome-extension-stripping'
import { chunkMutationSnapshot } from 'scenes/session-recordings/player/snapshot-processing/chunk-large-mutations'
import { decompressEvent } from 'scenes/session-recordings/player/snapshot-processing/decompress'
import {
    patchMetaEventIntoMobileData,
    patchMetaEventIntoWebData,
    ViewportResolution,
} from 'scenes/session-recordings/player/snapshot-processing/patch-meta-event'
import { keyForSource, SourceKey } from 'scenes/session-recordings/player/snapshot-processing/source-key'
import { throttleCapture } from 'scenes/session-recordings/player/snapshot-processing/throttle-capturing'

import {
    EncodedRecordingSnapshot,
    RecordingSnapshot,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
} from '~/types'

import { PostHogEE } from '../../../../../@posthog/ee/types'

const TOKEN_BUCKET_CONFIG = {
    rate: 100, // tokens per second
    capacity: 1000,
    minTokensPerAdd: 1,
    // Add a minimum time between adds to prevent burst flooding
    minTimeBetweenAdds: 10, // 10ms between adds
}

interface NodeTokenBucket {
    tokens: number
    lastRefill: number
    hasProcessedAdd: boolean
    lastAddTime: number // Track when we last allowed an add
}

const nodeTokenBuckets = new Map<number, NodeTokenBucket>()

function refillTokens(bucket: NodeTokenBucket, now: number): void {
    const timePassed = now - bucket.lastRefill
    const newTokens = Math.floor((timePassed * TOKEN_BUCKET_CONFIG.rate) / 1000)
    bucket.tokens = Math.min(TOKEN_BUCKET_CONFIG.capacity, bucket.tokens + newTokens)
    bucket.lastRefill = now
}

function canProcessAdd(nodeId: number, timestamp: number): boolean {
    let bucket = nodeTokenBuckets.get(nodeId)

    if (!bucket) {
        bucket = {
            tokens: TOKEN_BUCKET_CONFIG.capacity,
            lastRefill: timestamp,
            hasProcessedAdd: false,
            lastAddTime: 0,
        }
        nodeTokenBuckets.set(nodeId, bucket)
    }

    refillTokens(bucket, timestamp)

    // Always allow at least one add
    if (!bucket.hasProcessedAdd) {
        bucket.hasProcessedAdd = true
        bucket.lastAddTime = timestamp
        return true
    }

    // Enforce minimum time between adds
    if (timestamp - bucket.lastAddTime < TOKEN_BUCKET_CONFIG.minTimeBetweenAdds) {
        return false
    }

    // Check if we have enough tokens
    if (bucket.tokens >= TOKEN_BUCKET_CONFIG.minTokensPerAdd) {
        bucket.tokens -= TOKEN_BUCKET_CONFIG.minTokensPerAdd
        bucket.lastAddTime = timestamp
        return true
    }

    return false
}

export function processAllSnapshots(
    sources: SessionRecordingSnapshotSource[] | null,
    snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse> | null,
    viewportForTimestamp: (timestamp: number) => ViewportResolution | undefined,
    sessionRecordingId: string
): RecordingSnapshot[] {
    // Reset token buckets at the start of processing
    nodeTokenBuckets.clear()

    if (!sources || !snapshotsBySource) {
        return []
    }

    const seenHashes: Set<string> = new Set()
    const result: RecordingSnapshot[] = []
    const matchedExtensions = new Set<string>()

    let metaCount = 0
    let fullSnapshotCount = 0

    for (const source of sources) {
        const sourceKey = keyForSource(source)
        const sourceSnapshots = (snapshotsBySource?.[sourceKey]?.snapshots || []).sort(
            (a, b) => a.timestamp - b.timestamp
        )

        for (const snapshot of sourceSnapshots) {
            const { delay: _delay, ...delayFreeSnapshot } = snapshot

            const key = (snapshot as any).seen || cyrb53(JSON.stringify(delayFreeSnapshot))
            ;(snapshot as any).seen = key

            if (seenHashes.has(key)) {
                continue
            }
            seenHashes.add(key)

            if (snapshot.type === EventType.Meta) {
                metaCount += 1
            }

            if (snapshot.type === EventType.FullSnapshot) {
                fullSnapshotCount += 1
                // Reset token buckets on full snapshot
                nodeTokenBuckets.clear()

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
                            payload: {
                                extensions: Array.from(matchedExtensions),
                            },
                        },
                        timestamp: snapshot.timestamp,
                        windowId: snapshot.windowId,
                    })
                }
            } else if (
                snapshot.type === EventType.IncrementalSnapshot &&
                snapshot.data?.source === IncrementalSource.Mutation
            ) {
                // Filter adds based on token bucket
                const filteredData = {
                    ...snapshot.data,
                    adds: snapshot.data.adds.filter((add) => canProcessAdd(add.node.id, snapshot.timestamp)),
                    removes: snapshot.data.removes,
                    texts: snapshot.data.texts,
                    attributes: snapshot.data.attributes,
                }

                // Only include snapshot if it has any mutations
                if (
                    filteredData.adds.length > 0 ||
                    filteredData.removes.length > 0 ||
                    filteredData.texts.length > 0 ||
                    filteredData.attributes.length > 0
                ) {
                    result.push({
                        ...snapshot,
                        data: filteredData,
                    })
                }
                continue
            }

            result.push(snapshot)
        }
    }

    result.sort((a, b) => a.timestamp - b.timestamp)

    const needToPatchMeta = fullSnapshotCount > 0 && fullSnapshotCount > metaCount
    return needToPatchMeta ? patchMetaEventIntoWebData(result, viewportForTimestamp, sessionRecordingId) : result
}

let postHogEEModule: PostHogEE

function isRecordingSnapshot(x: unknown): x is RecordingSnapshot {
    return typeof x === 'object' && x !== null && 'type' in x && 'timestamp' in x
}

function hasAnyWireframes(snapshotData: Record<string, any>[]): boolean {
    return snapshotData.some((d) => {
        return isObject(d.data) && 'wireframes' in d.data
    })
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
    return postHogEEModule?.mobileReplay?.transformEventToWeb(currentEvent) || (currentEvent as eventWithTime)
}

export const parseEncodedSnapshots = async (
    items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[],
    sessionId: string
): Promise<RecordingSnapshot[]> => {
    if (!postHogEEModule) {
        postHogEEModule = await posthogEE()
    }

    const lineCount = items.length
    const unparseableLines: string[] = []
    let isMobileSnapshots = false

    const parsedLines: RecordingSnapshot[] = items.flatMap((l) => {
        if (!l) {
            // blob files have an empty line at the end
            return []
        }
        try {
            let snapshotLine: { windowId: string } | EncodedRecordingSnapshot
            if (typeof l === 'string') {
                // is loaded from blob or realtime storage
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
                // is loaded from blob or realtime storage
                snapshotData = snapshotLine['data']
            }

            if (!isMobileSnapshots) {
                isMobileSnapshots = hasAnyWireframes(snapshotData)
            }

            return snapshotData.flatMap((d: unknown) => {
                const snap = coerceToEventWithTime(d, sessionId)

                const baseSnapshot: RecordingSnapshot = {
                    windowId: snapshotLine['window_id'] || snapshotLine['windowId'],
                    ...snap,
                }

                // Apply chunking to the snapshot if needed
                return chunkMutationSnapshot(baseSnapshot)
            })
        } catch (e) {
            if (typeof l === 'string') {
                unparseableLines.push(l)
            }
            return []
        }
    })

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

    return isMobileSnapshots ? patchMetaEventIntoMobileData(parsedLines, sessionId) : parsedLines
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
