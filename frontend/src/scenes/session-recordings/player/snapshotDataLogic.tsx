import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { EventType } from '@posthog/rrweb-types'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { parseEncodedSnapshots } from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'
import { SourceKey, keyForSource } from 'scenes/session-recordings/player/snapshot-processing/source-key'
import { windowIdRegistryLogic } from 'scenes/session-recordings/player/windowIdRegistryLogic'

import '~/queries/utils'
import {
    RecordingSnapshot,
    SessionRecordingId,
    SessionRecordingSnapshotParams,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
    SnapshotSourceType,
} from '~/types'

import type { snapshotDataLogicType } from './snapshotDataLogicType'

const DEFAULT_V2_POLLING_INTERVAL_MS: number = 10000
const MAX_V2_POLLING_INTERVAL_MS = 60000
const POLLING_INACTIVITY_TIMEOUT_MS = 5 * MAX_V2_POLLING_INTERVAL_MS

export interface SnapshotLogicProps {
    sessionRecordingId: SessionRecordingId
    // allows disabling polling for new sources in tests
    blobV2PollingDisabled?: boolean
    accessToken?: string
}

/** Find which blob source index contains the given timestamp. Returns the index, clamped to bounds. */
function getBlobIndexForTimestamp(snapshotSources: SessionRecordingSnapshotSource[], timestamp: number): number {
    for (let i = 0; i < snapshotSources.length; i++) {
        const source = snapshotSources[i]
        const startTs = source.start_timestamp ? new Date(source.start_timestamp).getTime() : null
        const endTs = source.end_timestamp ? new Date(source.end_timestamp).getTime() : null
        if (startTs !== null && endTs !== null && timestamp >= startTs && timestamp <= endTs) {
            return i
        }
    }
    const firstStart = snapshotSources[0].start_timestamp
    if (firstStart && timestamp < new Date(firstStart).getTime()) {
        return 0
    }
    return snapshotSources.length - 1
}

export type LoadingPhase =
    | 'sequential' // Default: load from start (existing behavior)
    | 'find_target' // Loading blob window around target timestamp
    | 'find_fullsnapshot' // Loading backwards to find FullSnapshot

export const snapshotDataLogic = kea<snapshotDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'snapshotLogic', key]),
    props({} as SnapshotLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect((props: SnapshotLogicProps) => ({
        actions: [windowIdRegistryLogic({ sessionRecordingId: props.sessionRecordingId }), ['registerWindowId']],
        values: [
            windowIdRegistryLogic({ sessionRecordingId: props.sessionRecordingId }),
            ['uuidToIndex', 'getWindowId'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions({
        setSnapshots: (snapshots: RecordingSnapshot[]) => ({ snapshots }),
        loadSnapshots: true,
        loadSnapshotSources: (breakpointLength?: number) => ({ breakpointLength }),
        loadNextSnapshotSource: true,
        loadSnapshotsForSource: (sources: Pick<SessionRecordingSnapshotSource, 'source' | 'blob_key'>[]) => ({
            sources,
        }),
        maybeStartPolling: true,
        startPolling: true,
        stopPolling: true,
        setPollingInterval: (intervalMs: number) => ({ intervalMs }),
        resetPollingInterval: true,
        // Timestamp-based loading actions
        setTargetTimestamp: (timestamp: number | null) => ({ timestamp }),
        setLoadingPhase: (phase: LoadingPhase) => ({ phase }),
        resetTimestampLoading: true,
        // Playability tracking - records FullSnapshot + Meta timestamps before processing clears cache
        recordPlayabilityMarkers: (markers: { fullSnapshots: number[]; metas: number[] }) => ({ markers }),
    }),
    reducers(() => ({
        snapshotsBySourceSuccessCount: [
            0,
            {
                loadSnapshotsForSourceSuccess: (state) => state + 1,
            },
        ],
        loadingSources: [
            [] as Pick<SessionRecordingSnapshotSource, 'source' | 'blob_key' | 'start_timestamp' | 'end_timestamp'>[],
            {
                loadSnapshotsForSource: (_, { sources }) => sources,
                loadSnapshotsForSourceSuccess: () => [],
                loadSnapshotsForSourceFailure: () => [],
            },
        ],
        pollingInterval: [
            DEFAULT_V2_POLLING_INTERVAL_MS,
            {
                setPollingInterval: (_, { intervalMs }) => intervalMs,
                resetPollingInterval: () => DEFAULT_V2_POLLING_INTERVAL_MS,
            },
        ],
        isPolling: [
            false,
            {
                startPolling: () => true,
                stopPolling: () => false,
            },
        ],
        // Timestamp-based loading state
        targetTimestamp: [
            null as number | null,
            {
                setTargetTimestamp: (_, { timestamp }) => timestamp,
                resetTimestampLoading: () => null,
            },
        ],
        loadingPhase: [
            'sequential' as LoadingPhase,
            {
                setLoadingPhase: (_, { phase }) => phase,
                resetTimestampLoading: () => 'sequential',
            },
        ],
        // Tracks FullSnapshot + Meta timestamps before processing clears cache
        // This persists even after processAllSnapshots clears snapshotsBySource
        // NOTE: Do NOT reset on resetTimestampLoading - these markers should persist
        // for the lifetime of the recording since they're metadata about the data itself
        playabilityMarkers: [
            { fullSnapshots: [] as number[], metas: [] as number[] },
            {
                recordPlayabilityMarkers: (state, { markers }) => ({
                    fullSnapshots: [...new Set([...state.fullSnapshots, ...markers.fullSnapshots])].sort(
                        (a, b) => a - b
                    ),
                    metas: [...new Set([...state.metas, ...markers.metas])].sort((a, b) => a - b),
                }),
                // Only reset when loading a new recording (logic is keyed by sessionRecordingId)
            },
        ],
    })),
    loaders(({ values, props, cache, actions }) => ({
        snapshotSources: [
            null as SessionRecordingSnapshotSource[] | null,
            {
                loadSnapshotSources: async ({ breakpointLength }, breakpoint) => {
                    if (breakpointLength) {
                        await breakpoint(breakpointLength)
                    }

                    const headers: Record<string, string> = {}
                    if (props.accessToken) {
                        headers.Authorization = `Bearer ${props.accessToken}`
                    }

                    const response = await api.recordings.listSnapshotSources(props.sessionRecordingId, headers)

                    if (!response || !response.sources) {
                        return []
                    }
                    const anyBlobV2 = response.sources.some((s) => s.source === SnapshotSourceType.blob_v2)

                    if (anyBlobV2) {
                        return response.sources.filter((s) => s.source === SnapshotSourceType.blob_v2)
                    }
                    return response.sources.filter((s) => s.source !== SnapshotSourceType.blob_v2)
                },
            },
        ],
        snapshotsForSource: [
            null as SessionRecordingSnapshotSourceResponse | null,
            {
                loadSnapshotsForSource: async ({ sources }, breakpoint) => {
                    let params: SessionRecordingSnapshotParams

                    const source = sources[0]

                    if (source.source === SnapshotSourceType.blob_v2_lts) {
                        if (!source.blob_key) {
                            throw new Error('Missing key')
                        }
                        params = { blob_key: source.blob_key, source: 'blob_v2_lts' }
                    } else if (source.source === SnapshotSourceType.blob_v2) {
                        // they all have to be blob_v2
                        if (sources.some((s) => s.source !== SnapshotSourceType.blob_v2)) {
                            throw new Error('Unsupported source for multiple sources')
                        }
                        params = {
                            source: 'blob_v2',
                            // so the caller has to make sure these are in order!
                            start_blob_key: sources[0].blob_key,
                            end_blob_key: sources[sources.length - 1].blob_key,
                        }
                    } else if (source.source === SnapshotSourceType.file) {
                        // no need to load a file source, it is already loaded
                        return { source }
                    } else {
                        throw new Error(`Unsupported source: ${source.source}`)
                    }

                    await breakpoint(1)

                    const headers: Record<string, string> = {}
                    if (props.accessToken) {
                        headers.Authorization = `Bearer ${props.accessToken}`
                    }

                    const response = await api.recordings.getSnapshots(
                        props.sessionRecordingId,
                        { decompress: false, ...params },
                        headers
                    )

                    // Create a local copy of the registry state for synchronous lookups during parsing
                    const localWindowIds: Record<string, number> = { ...values.uuidToIndex }
                    const registerWindowIdCallback = (uuid: string): number => {
                        if (uuid in localWindowIds) {
                            return localWindowIds[uuid]
                        }
                        const index = Object.keys(localWindowIds).length + 1
                        localWindowIds[uuid] = index
                        return index
                    }

                    // sorting is very cheap for already sorted lists
                    const parsedSnapshots = (
                        await parseEncodedSnapshots(
                            response,
                            props.sessionRecordingId,
                            posthog,
                            registerWindowIdCallback
                        )
                    ).sort((a, b) => a.timestamp - b.timestamp)

                    // Sync any newly discovered window IDs to the shared registry
                    for (const uuid of Object.keys(localWindowIds)) {
                        if (!(uuid in values.uuidToIndex)) {
                            actions.registerWindowId(uuid)
                        }
                    }
                    // we store the data in the cache because we want to avoid copying this data as much as possible
                    // and kea's immutability means we were copying all the data on every snapshot call
                    if (!cache.snapshotsBySource) {
                        cache.snapshotsBySource = {}
                    }

                    // it doesn't matter which source we use as the key, since we combine the snapshots anyway
                    const storageKey = keyForSource(sources[0])
                    cache.snapshotsBySource[storageKey] = { snapshots: parsedSnapshots }

                    // but we do want to mark the sources as loaded
                    sources.forEach((s) => {
                        const k = keyForSource(s)
                        // we just need something against each key so we don't load it again
                        cache.snapshotsBySource[k] = cache.snapshotsBySource[k] || {}
                        cache.snapshotsBySource[k].sourceLoaded = true
                    })

                    return { sources }
                },
            },
        ],
    })),
    listeners(({ values, actions, cache, props }) => ({
        setTargetTimestamp: ({ timestamp }) => {
            // Skip if same timestamp (debounce redundant calls)
            if (timestamp === cache.lastTargetTimestamp) {
                return
            }
            cache.lastTargetTimestamp = timestamp

            if (timestamp !== null) {
                // If we don't have sources loaded yet, always start with find_target
                // hasPlayableFullSnapshot returns true when no sources (safety default)
                // but we need to actually load data first
                if (!values.snapshotSources?.length) {
                    cache.timestampLoadingRange = undefined
                    cache.timestampLoadingBlobCount = undefined
                    cache.timestampLoadingStartTime = undefined
                    actions.setLoadingPhase('find_target')
                    return
                }

                // Check if we already have playable data for this new timestamp
                // The selector will recalculate with the new targetTimestamp value
                // (reducer runs before listener, so values.targetTimestamp is already updated)
                if (values.hasPlayableFullSnapshot) {
                    // Keep in sequential phase - we have the data needed
                    if (values.loadingPhase !== 'sequential') {
                        actions.setLoadingPhase('sequential')
                    }
                } else {
                    // If already in sequential phase, don't reset - sequential loading will eventually
                    // make this timestamp playable. Only reset if we're in an earlier phase.
                    if (values.loadingPhase !== 'sequential') {
                        // Reset timestamp-based loading state for clean start
                        cache.timestampLoadingRange = undefined
                        cache.timestampLoadingBlobCount = undefined
                        cache.timestampLoadingStartTime = undefined
                        actions.setLoadingPhase('find_target')
                    }
                }
            }
        },

        setSnapshots: ({ snapshots }: { snapshots: RecordingSnapshot[] }) => {
            cache.snapshotsBySource = {
                'file-file': {
                    snapshots: snapshots,
                    source: { source: SnapshotSourceType.file },
                    sourceLoaded: true,
                },
            }
            // Set sources first, then trigger the success action
            // Otherwise processSnapshotsAsync will see null sources
            actions.loadSnapshotSourcesSuccess([{ source: SnapshotSourceType.file }])
            actions.loadSnapshotsForSourceSuccess({
                source: { source: SnapshotSourceType.file },
            })
        },

        loadSnapshots: () => {
            // This kicks off the loading chain
            if (!values.snapshotSourcesLoading) {
                actions.loadSnapshotSources()
            }
        },

        loadSnapshotSourcesSuccess: ({ snapshotSources }) => {
            const currentSourceKeys = snapshotSources
                .map((s) => s.blob_key)
                .filter(Boolean)
                .sort()
            const previousSourceKeys = cache.previousSourceKeys || []

            const sourcesChanged =
                currentSourceKeys.length !== previousSourceKeys.length ||
                currentSourceKeys.some((key, i) => key !== previousSourceKeys[i])

            cache.previousSourceKeys = currentSourceKeys

            if (sourcesChanged) {
                actions.resetPollingInterval()
                cache.lastSourcesChangeTime = Date.now()
                actions.stopPolling()
            } else {
                const currentInterval = values.pollingInterval
                const newInterval = Math.min(currentInterval * 2, MAX_V2_POLLING_INTERVAL_MS)
                actions.setPollingInterval(newInterval)
            }

            actions.loadNextSnapshotSource()
        },

        loadSnapshotsForSourceSuccess: ({ snapshotsForSource }) => {
            const sources = values.snapshotSources
            const sourceKey = snapshotsForSource.sources
                ? keyForSource(snapshotsForSource.sources[0])
                : keyForSource(snapshotsForSource.source)
            const snapshotsData = (cache.snapshotsBySource || {})[sourceKey]
            const snapshots = snapshotsData?.snapshots || []

            // Extract playability markers BEFORE coordinator's processing clears snapshots
            // This must happen synchronously before any async processing
            const isTimestampBased = values.featureFlags[FEATURE_FLAGS.REPLAY_TIMESTAMP_BASED_LOADING] === 'test'
            if (isTimestampBased && snapshots.length > 0) {
                const fullSnapshotTs = snapshots
                    .filter((s: RecordingSnapshot) => s.type === EventType.FullSnapshot)
                    .map((s: RecordingSnapshot) => s.timestamp)
                const metaTs = snapshots
                    .filter((s: RecordingSnapshot) => s.type === EventType.Meta)
                    .map((s: RecordingSnapshot) => s.timestamp)

                if (fullSnapshotTs.length > 0 || metaTs.length > 0) {
                    actions.recordPlayabilityMarkers({ fullSnapshots: fullSnapshotTs, metas: metaTs })
                }
            }

            if (!snapshots.length && sources?.length === 1 && sources[0].source !== SnapshotSourceType.file) {
                // We got only a single source to load, loaded it successfully, but it had no snapshots.
                posthog.capture('recording_snapshots_v2_empty_response', {
                    source: sources[0],
                })
            }

            // For timestamp-based loading: after initial batch, check for FullSnapshot and advance phase
            if (values.loadingPhase === 'find_target' && values.targetTimestamp !== null) {
                // After loading initial batch, check for FullSnapshot
                actions.setLoadingPhase('find_fullsnapshot')
            }

            // if not then whenever we load a set of data, we try to load the next set right away
            actions.loadNextSnapshotSource()
        },

        maybeStartPolling: () => {
            if (props.blobV2PollingDisabled || !values.allSourcesLoaded || values.isPolling || document.hidden) {
                return
            }

            const lastChangeTime = cache.lastSourcesChangeTime || Date.now()
            const timeSinceLastChange = Date.now() - lastChangeTime

            if (timeSinceLastChange >= POLLING_INACTIVITY_TIMEOUT_MS) {
                return
            }

            actions.startPolling()
            actions.loadSnapshotSources(values.pollingInterval)
        },

        loadNextSnapshotSource: async (_, breakpoint) => {
            if (values.snapshotsForSourceLoading) {
                return
            }

            await breakpoint(1)

            const sources = values.snapshotSources
            if (!sources?.length) {
                return
            }

            const isSourceLoaded = (source: SessionRecordingSnapshotSource): boolean => {
                const sourceKey = keyForSource(source)
                return !!cache.snapshotsBySource?.[sourceKey]?.sourceLoaded
            }

            const getUnloadedSources = (): SessionRecordingSnapshotSource[] => {
                return sources.filter((s) => s.source !== SnapshotSourceType.file && !isSourceLoaded(s))
            }

            // Check if timestamp-based loading is enabled
            const isTimestampBased = values.featureFlags[FEATURE_FLAGS.REPLAY_TIMESTAMP_BASED_LOADING] === 'test'
            const hasBlobV2 = sources.some((s) => s.source === SnapshotSourceType.blob_v2)

            if (isTimestampBased && hasBlobV2 && values.targetTimestamp !== null) {
                // Safety timeout: if timestamp-based loading takes too long, fall back to sequential
                const TIMESTAMP_LOADING_TIMEOUT_MS = 30000
                const loadingStartTime = cache.timestampLoadingStartTime || 0
                if (loadingStartTime > 0 && performance.now() - loadingStartTime > TIMESTAMP_LOADING_TIMEOUT_MS) {
                    posthog.capture('recording_timestamp_loading_timeout', {
                        targetTimestamp: values.targetTimestamp,
                        phase: values.loadingPhase,
                        elapsedMs: performance.now() - loadingStartTime,
                    })
                    // Clear target timestamp so player can start playing
                    actions.resetTimestampLoading()
                    // Fall through to sequential loading
                }

                // Timestamp-based loading state machine
                switch (values.loadingPhase) {
                    case 'find_target': {
                        // Load window of blobs around target: [target-2, target+8]
                        const targetIndex = values.blobIndexForTimestamp(values.targetTimestamp)
                        if (targetIndex === null) {
                            // Clear target timestamp so player can start playing
                            actions.resetTimestampLoading()
                            return actions.loadNextSnapshotSource()
                        }

                        const startIndex = Math.max(0, targetIndex - 2)
                        const endIndex = Math.min(sources.length - 1, targetIndex + 7)
                        const initialBatch = sources
                            .slice(startIndex, endIndex + 1)
                            .filter((s) => s.source !== SnapshotSourceType.file && !isSourceLoaded(s))

                        cache.timestampLoadingRange = { start: startIndex, end: endIndex }
                        cache.timestampLoadingBlobCount = initialBatch.length
                        cache.timestampLoadingStartTime = performance.now()

                        if (initialBatch.length > 0) {
                            return actions.loadSnapshotsForSource(initialBatch)
                        }
                        // Initial batch already loaded, check for FullSnapshot
                        actions.setLoadingPhase('find_fullsnapshot')
                        return actions.loadNextSnapshotSource()
                    }

                    case 'find_fullsnapshot': {
                        // Race condition check: if cache was reset (by a new setTargetTimestamp), restart from find_target
                        if (!cache.timestampLoadingRange) {
                            actions.setLoadingPhase('find_target')
                            return actions.loadNextSnapshotSource()
                        }

                        if (values.hasPlayableFullSnapshot) {
                            // FullSnapshot found with continuous coverage - clear target and switch to sequential
                            const timeToPlayable = cache.timestampLoadingStartTime
                                ? performance.now() - cache.timestampLoadingStartTime
                                : null
                            posthog.capture('recording_timestamp_loading_playable', {
                                targetTimestamp: values.targetTimestamp,
                                blobsLoadedForFullSnapshot: cache.timestampLoadingBlobCount || 0,
                                timeToPlayableMs: timeToPlayable,
                            })
                            // Switch to sequential loading to load remaining blobs
                            // Keep targetTimestamp so the player knows where to seek
                            // isWaitingForPlayableFullSnapshot returns false when hasPlayableFullSnapshot is true
                            actions.setLoadingPhase('sequential')
                            return actions.loadNextSnapshotSource()
                        }

                        const range = cache.timestampLoadingRange

                        // Check if we have any FullSnapshot (even without continuous coverage)
                        // If so, we need to fill the gap between FullSnapshot and target
                        const fullSnapshotInfo = values.findNearestFullSnapshot
                        if (fullSnapshotInfo) {
                            // We have a FullSnapshot but there's a gap - fill it
                            const gapStart = fullSnapshotInfo.blobIndex + 1
                            const gapEnd = range.start - 1

                            if (gapStart <= gapEnd) {
                                // Load gap blobs (up to 10 at a time)
                                const gapBatchEnd = Math.min(gapEnd, gapStart + 9)
                                const gapBatch = sources
                                    .slice(gapStart, gapBatchEnd + 1)
                                    .filter((s) => s.source !== SnapshotSourceType.file && !isSourceLoaded(s))

                                // Update range to include gap we're filling
                                cache.timestampLoadingRange = {
                                    start: Math.min(range.start, gapStart),
                                    end: range.end,
                                }
                                cache.timestampLoadingBlobCount =
                                    (cache.timestampLoadingBlobCount || 0) + gapBatch.length

                                if (gapBatch.length > 0) {
                                    return actions.loadSnapshotsForSource(gapBatch)
                                }
                            }
                        }

                        // Need to load earlier blobs to find FullSnapshot
                        // Find the earliest unloaded blob before our current range
                        let searchEnd = range.start - 1
                        while (searchEnd >= 0 && isSourceLoaded(sources[searchEnd])) {
                            searchEnd--
                        }

                        if (searchEnd >= 0) {
                            const searchStart = Math.max(0, searchEnd - 9)
                            const searchBatch = sources
                                .slice(searchStart, searchEnd + 1)
                                .filter((s) => s.source !== SnapshotSourceType.file && !isSourceLoaded(s))

                            cache.timestampLoadingRange = { start: searchStart, end: range.end }
                            cache.timestampLoadingBlobCount =
                                (cache.timestampLoadingBlobCount || 0) + searchBatch.length

                            if (searchBatch.length > 0) {
                                return actions.loadSnapshotsForSource(searchBatch)
                            }
                        }

                        // No more previous blobs - proceed with sequential loading anyway
                        posthog.capture('recording_timestamp_loading_no_fullsnapshot', {
                            targetTimestamp: values.targetTimestamp,
                            totalBlobsSearched: cache.timestampLoadingBlobCount || 0,
                        })
                        // Clear target timestamp so player can start playing even without optimal FullSnapshot
                        actions.resetTimestampLoading()
                        return actions.loadNextSnapshotSource()
                    }

                    case 'sequential':
                    default: {
                        // When timestamp-based loading switches to sequential, load forward first then backward
                        // This prevents the player from jumping back to the beginning
                        const range = cache.timestampLoadingRange

                        if (range) {
                            // First: load forward from range.end+1 to the end of sources
                            const forwardSources = sources
                                .slice(range.end + 1)
                                .filter((s) => s.source !== SnapshotSourceType.file && !isSourceLoaded(s))

                            if (forwardSources.length > 0) {
                                return actions.loadSnapshotsForSource(forwardSources.slice(0, 10))
                            }

                            // Second: load backward from range.start-1 to start
                            // Load from just-before-target toward the beginning
                            // Use slice(-10) to get the last N items (closest to target) in original order
                            // This maintains API compatibility while loading data nearest to playback first
                            const backwardSources = sources
                                .slice(0, range.start)
                                .filter((s) => s.source !== SnapshotSourceType.file && !isSourceLoaded(s))

                            if (backwardSources.length > 0) {
                                // Take the last 10 unloaded sources (closest to the target)
                                const batchToLoad = backwardSources.slice(-10)
                                return actions.loadSnapshotsForSource(batchToLoad)
                            }

                            // All done - clear the range
                            cache.timestampLoadingRange = undefined
                        }
                        // Fall through to regular sequential loading below
                        break
                    }
                }
            }

            // Sequential loading (default behavior or fallback)
            if (hasBlobV2) {
                const nextSourcesToLoad = getUnloadedSources()

                if (nextSourcesToLoad.length > 0) {
                    return actions.loadSnapshotsForSource(nextSourcesToLoad.slice(0, 10))
                }

                actions.maybeStartPolling()
            } else {
                // V1 behavior unchanged
                const nextSourceToLoad = sources.find((s) => {
                    const sourceKey = keyForSource(s)
                    return !cache.snapshotsBySource?.[sourceKey]?.sourceLoaded && s.source !== SnapshotSourceType.file
                })

                if (nextSourceToLoad) {
                    return actions.loadSnapshotsForSource([nextSourceToLoad])
                }
            }
        },
    })),
    selectors(({ cache }) => ({
        snapshotsLoading: [
            (s) => [s.snapshotSourcesLoading, s.snapshotsForSourceLoading, s.snapshotsBySources],
            (
                snapshotSourcesLoading: boolean,
                snapshotsForSourceLoading: boolean,
                snapshotsBySources: Record<string, RecordingSnapshot[]>
            ): boolean => {
                const snapshots = Object.values(snapshotsBySources).flat()
                return snapshots?.length === 0 && (snapshotSourcesLoading || snapshotsForSourceLoading)
            },
        ],

        snapshotsLoaded: [(s) => [s.snapshotSources], (snapshotSources): boolean => !!snapshotSources],

        snapshotsBySources: [
            (s) => [s.snapshotsBySourceSuccessCount],
            (
                snapshotsBySourceSuccessCount: number
            ): Record<SourceKey, SessionRecordingSnapshotSourceResponse> & { _count?: number } => {
                if (!cache.snapshotsBySource) {
                    return {}
                }

                // KLUDGE: we keep the data in a cache so we can avoid creating large objects every time something changes
                // KLUDGE: but if we change the data without changing the object instance then dependents don't recalculate
                if (cache.snapshotsBySource['_count'] !== snapshotsBySourceSuccessCount) {
                    // so we make a new object instance when the count changes
                    // technically this should only be called when success count changes anyway...
                    // but let's be very careful, it is relatively free to track the count
                    // Create shallow copy to trigger dependent selectors
                    // IMPORTANT: This must preserve the snapshot arrays from previous batches
                    const newCache: Record<string, any> = {}
                    for (const key of Object.keys(cache.snapshotsBySource)) {
                        newCache[key] = cache.snapshotsBySource[key]
                    }
                    newCache['_count'] = snapshotsBySourceSuccessCount
                    cache.snapshotsBySource = newCache
                }
                return cache.snapshotsBySource
            },
        ],

        isLoadingSnapshots: [
            (s) => [s.loadingSources],
            (loadingSources): boolean => {
                return loadingSources.length > 0
            },
        ],

        allSourcesLoaded: [
            (s) => [s.snapshotSources, s.snapshotsBySourceSuccessCount],
            (snapshotSources): boolean => {
                if (!snapshotSources || snapshotSources.length === 0) {
                    return false
                }
                return snapshotSources.every((source) => {
                    const sourceKey = keyForSource(source)
                    return cache.snapshotsBySource?.[sourceKey]?.sourceLoaded
                })
            },
        ],

        // Timestamp-based loading selectors
        blobIndexForTimestamp: [
            (s) => [s.snapshotSources],
            (snapshotSources): ((timestamp: number) => number | null) => {
                return (timestamp: number): number | null => {
                    if (!snapshotSources?.length) {
                        return null
                    }
                    return getBlobIndexForTimestamp(snapshotSources, timestamp)
                }
            },
        ],

        // Find the nearest FullSnapshot before target timestamp (used for gap filling)
        findNearestFullSnapshot: [
            (s) => [s.playabilityMarkers, s.blobIndexForTimestamp, s.targetTimestamp],
            (
                playabilityMarkers: { fullSnapshots: number[]; metas: number[] },
                blobIndexForTimestamp: (timestamp: number) => number | null,
                targetTimestamp: number | null
            ): { blobIndex: number; timestamp: number } | null => {
                if (!targetTimestamp) {
                    return null
                }

                const { fullSnapshots } = playabilityMarkers

                // Find FullSnapshots at or before target timestamp
                const validFullSnapshots = fullSnapshots.filter((ts) => ts <= targetTimestamp)
                if (validFullSnapshots.length === 0) {
                    return null
                }

                // Get the nearest (latest) FullSnapshot before target
                const nearestFullSnapshotTs = validFullSnapshots[validFullSnapshots.length - 1]
                const blobIndex = blobIndexForTimestamp(nearestFullSnapshotTs)
                if (blobIndex === null) {
                    return null
                }

                return { blobIndex, timestamp: nearestFullSnapshotTs }
            },
        ],

        hasPlayableFullSnapshot: [
            (s) => [s.playabilityMarkers, s.snapshotsBySources, s.snapshotSources, s.targetTimestamp],
            (
                playabilityMarkers: { fullSnapshots: number[]; metas: number[] },
                snapshotsBySources: Record<SourceKey, SessionRecordingSnapshotSourceResponse>,
                snapshotSources: SessionRecordingSnapshotSource[] | null,
                targetTimestamp: number | null
            ): boolean => {
                if (!targetTimestamp || !snapshotSources?.length) {
                    return true // No target or sources, default playable
                }

                const { fullSnapshots } = playabilityMarkers

                const isSourceLoaded = (index: number): boolean => {
                    const source = snapshotSources[index]
                    if (!source) {
                        return false
                    }
                    const sourceKey = keyForSource(source)
                    return !!snapshotsBySources[sourceKey]?.sourceLoaded
                }

                // Find FullSnapshots at or before target timestamp
                const validFullSnapshots = fullSnapshots.filter((ts) => ts <= targetTimestamp)
                if (validFullSnapshots.length === 0) {
                    // Edge case: target is at or before the first FullSnapshot (e.g., seeking to t=0)
                    // If we have blob 0 loaded AND there's at least one FullSnapshot, we can play from it
                    // rrweb will start from the first available FullSnapshot
                    if (fullSnapshots.length > 0) {
                        // Check if blob 0 (first blob) is loaded - it should contain the first FullSnapshot
                        if (isSourceLoaded(0)) {
                            const firstFullSnapshotTs = fullSnapshots[0]
                            // If target is within 1 second before the first FullSnapshot, consider playable
                            // This handles the common case where recording starts slightly before first FullSnapshot
                            if (targetTimestamp >= firstFullSnapshotTs - 1000) {
                                return true
                            }
                        }
                    }
                    return false // No FullSnapshot before target
                }

                // Find the nearest FullSnapshot before target (largest timestamp <= targetTimestamp)
                const nearestFullSnapshotTs = validFullSnapshots[validFullSnapshots.length - 1]

                const fullSnapshotBlobIndex = getBlobIndexForTimestamp(snapshotSources, nearestFullSnapshotTs)
                const targetBlobIndex = getBlobIndexForTimestamp(snapshotSources, targetTimestamp)

                // Check continuous coverage from FullSnapshot blob to target blob
                // Also check one blob before for potential Meta event
                const startCheck = Math.max(0, fullSnapshotBlobIndex - 1)
                for (let i = startCheck; i <= targetBlobIndex; i++) {
                    if (!isSourceLoaded(i)) {
                        return false // Gap in coverage
                    }
                }

                return true
            },
        ],

        // Returns true when timestamp-based loading is active and we don't have a playable FullSnapshot yet
        // The player should stay in buffering state when this is true
        isWaitingForPlayableFullSnapshot: [
            (s) => [s.targetTimestamp, s.hasPlayableFullSnapshot],
            (targetTimestamp: number | null, hasPlayableFullSnapshot: boolean): boolean => {
                if (targetTimestamp === null) {
                    return false // Not doing timestamp-based loading
                }
                if (hasPlayableFullSnapshot) {
                    return false // We have a playable FullSnapshot, good to go
                }
                // We have a target timestamp but no playable FullSnapshot yet
                return true
            },
        ],
    })),
    afterMount(({ actions, cache }) => {
        cache.disposables.add(() => {
            const handleVisibilityChange = (): void => {
                if (document.hidden) {
                    actions.stopPolling()
                } else {
                    actions.maybeStartPolling()
                }
            }

            document.addEventListener('visibilitychange', handleVisibilityChange)

            return () => {
                document.removeEventListener('visibilitychange', handleVisibilityChange)
            }
        }, 'visibilityChangeHandler')
    }),
    beforeUnmount(({ cache }) => {
        cache.snapshotsBySource = undefined
        cache.previousSourceKeys = undefined
        cache.lastSourcesChangeTime = undefined
        cache.timestampLoadingRange = undefined
        cache.timestampLoadingBlobCount = undefined
        cache.timestampLoadingStartTime = undefined
        cache.lastTargetTimestamp = undefined
    }),
])
