import posthogEE from '@posthog/ee/exports'
import { EventType, eventWithTime, fullSnapshotEvent } from '@posthog/rrweb-types'
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

const seenId: string | null = null
const processSnapshots = new Map<SourceKey, RecordingSnapshot[]>()

export function processAllSnapshots(
    sources: SessionRecordingSnapshotSource[] | null,
    snapshotsBySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse> | null,
    viewportForTimestamp: (timestamp: number) => ViewportResolution | undefined,
    sessionRecordingId: string
): RecordingSnapshot[] {
    if (!sources || !snapshotsBySource) {
        return []
    }

    if (seenId !== sessionRecordingId) {
        processSnapshots.clear()
    }

    const result: RecordingSnapshot[] = []
    const matchedExtensions = new Set<string>()
    const seenHashes: Set<string> = new Set()

    let metaCount = 0
    let fullSnapshotCount = 0

    // we loop over this data as little as possible,
    // since it could be large and processed more than once,
    // so we need to do as little as possible, as fast as possible
    for (const source of sources) {
        const sourceKey = keyForSource(source)

        if (processSnapshots.has(sourceKey)) {
            // If we already processed this source, skip it
            // doing push.apply to mutate the original array
            // and avoid a spread on a large array
            // eslint-disable-next-line prefer-spread
            result.push.apply(result, processSnapshots.get(sourceKey)!)
            continue
        }

        // sorting is very cheap for already sorted lists
        const sourceSnapshots = (snapshotsBySource?.[sourceKey]?.snapshots || []).sort(
            (a, b) => a.timestamp - b.timestamp
        )

        const sourceResult: RecordingSnapshot[] = []

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

            // Process chrome extension data
            if (snapshot.type === EventType.FullSnapshot) {
                fullSnapshotCount += 1

                const fullSnapshot = snapshot as RecordingSnapshot & fullSnapshotEvent & eventWithTime

                if (
                    stripChromeExtensionDataFromNode(
                        fullSnapshot.data.node,
                        Object.keys(CHROME_EXTENSION_DENY_LIST),
                        matchedExtensions
                    )
                ) {
                    // Add the custom event at the start of the result array
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
            }

            sourceResult.push(snapshot)
        }

        processSnapshots.set(sourceKey, sourceResult)
        // doing push.apply to mutate the original array
        // and avoid a spread on a large array
        // eslint-disable-next-line prefer-spread
        result.push.apply(result, sourceResult)
    }

    // sorting is very cheap for already sorted lists
    result.sort((a, b) => a.timestamp - b.timestamp)

    // Optional second pass: patch meta-events on the sorted array
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
