import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

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

import { LoadingScheduler } from './snapshot-store/LoadingScheduler'
import { SnapshotStore } from './snapshot-store/SnapshotStore'
import { SourceLoadingState } from './snapshot-store/types'
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
        setTargetTimestamp: (timestamp: number | null) => ({ timestamp }),
        updatePlaybackPosition: (timestamp: number) => ({ timestamp }),
        setPlayerActive: (active: boolean) => ({ active }),
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

                    // Mark each source as loaded so the legacy path doesn't re-fetch them.
                    // The store path tracks this via SnapshotStore entries instead.
                    if (!cache.useSnapshotStore) {
                        sources.forEach((s) => {
                            const k = keyForSource(s)
                            cache.snapshotsBySource[k] = cache.snapshotsBySource[k] || {}
                            cache.snapshotsBySource[k].sourceLoaded = true
                        })
                    }

                    return { sources }
                },
            },
        ],
    })),
    listeners(({ values, actions, cache, props }) => ({
        setTargetTimestamp: ({ timestamp }) => {
            if (!cache.useSnapshotStore || !cache.scheduler || !cache.store) {
                return
            }
            if (timestamp !== null) {
                cache.playbackPosition = timestamp

                const currentMode = cache.scheduler.currentMode
                // Don't re-seek to the same target
                if (currentMode.kind === 'seek' && currentMode.targetTimestamp === timestamp) {
                    return
                }
                // If we can already play at this position (data is loaded), no need to seek —
                // this handles segment transitions during normal forward playback
                if (cache.store?.canPlayAt(timestamp)) {
                    actions.loadNextSnapshotSource()
                    return
                }
                // Don't enter seek mode when at source 0 and already in buffer_ahead mode —
                // buffer_ahead loading already starts from the beginning
                const targetIndex = cache.store?.getSourceIndexForTimestamp(timestamp) ?? 0
                if (targetIndex === 0 && currentMode.kind === 'buffer_ahead') {
                    actions.loadNextSnapshotSource()
                    return
                }

                cache.scheduler.seekTo(timestamp)
                actions.loadNextSnapshotSource()
            }
        },

        updatePlaybackPosition: ({ timestamp }) => {
            if (!cache.useSnapshotStore) {
                return
            }
            cache.playbackPosition = timestamp
            // Trigger loading if the buffer ahead needs filling
            actions.loadNextSnapshotSource()
        },

        setPlayerActive: ({ active }) => {
            cache.playerActive = active
            if (active && cache.useSnapshotStore) {
                actions.loadNextSnapshotSource()
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

            // Initialize the snapshot store with sources when flag is on.
            // Only call setSources when sources actually changed — otherwise it wipes
            // all loaded/evicted entries, causing a full reload cycle on every poll.
            if (cache.useSnapshotStore && sourcesChanged) {
                cache.store.setSources(snapshotSources)
            }

            actions.loadNextSnapshotSource()
        },

        loadSnapshotsForSourceSuccess: ({ snapshotsForSource }) => {
            cache.loadFailureCount = 0
            const sources = values.snapshotSources
            const sourceKey = snapshotsForSource.sources
                ? keyForSource(snapshotsForSource.sources[0])
                : keyForSource(snapshotsForSource.source)
            const snapshotsData = (cache.snapshotsBySource || {})[sourceKey]
            const snapshots = snapshotsData?.snapshots || []

            if (!snapshots.length && sources?.length === 1 && sources[0].source !== SnapshotSourceType.file) {
                // We got only a single source to load, loaded it successfully, but it had no snapshots.
                posthog.capture('recording_snapshots_v2_empty_response', {
                    source: sources[0],
                })
            }

            // When using SnapshotStore, split batch snapshots across sources and store
            if (cache.useSnapshotStore && sources) {
                const loadedSources = snapshotsForSource.sources || [snapshotsForSource.source]
                // The API returns all snapshots for the batch combined under the first source key.
                // Split them across individual sources using sorted sequential assignment
                // to avoid dropping snapshots that fall in timestamp gaps between sources.
                const batchKey = keyForSource(loadedSources[0])
                const batchData = (cache.snapshotsBySource || {})[batchKey]
                const allBatchSnapshots: RecordingSnapshot[] = batchData?.snapshots || []

                // Build ordered list of (sourceIndex, endMs) for the loaded sources
                const sourceEntries: { sourceIndex: number; endMs: number }[] = []
                for (const loaded of loadedSources) {
                    const sourceIndex = sources.findIndex((s) => keyForSource(s) === keyForSource(loaded))
                    if (sourceIndex < 0) {
                        continue
                    }
                    const entry = cache.store.getEntry(sourceIndex)
                    if (!entry) {
                        continue
                    }
                    sourceEntries.push({ sourceIndex, endMs: entry.endMs })
                }
                sourceEntries.sort((a, b) => a.endMs - b.endMs)

                // Assign each snapshot to the first source whose endMs >= snapshot timestamp.
                // Snapshots are already sorted by timestamp from the API.
                const buckets = new Map<number, RecordingSnapshot[]>()
                for (const se of sourceEntries) {
                    buckets.set(se.sourceIndex, [])
                }

                let seIdx = 0
                for (const snap of allBatchSnapshots) {
                    // Advance to the source that covers this timestamp
                    while (seIdx < sourceEntries.length - 1 && snap.timestamp > sourceEntries[seIdx].endMs) {
                        seIdx++
                    }
                    buckets.get(sourceEntries[seIdx].sourceIndex)!.push(snap)
                }

                for (const se of sourceEntries) {
                    cache.store.markLoaded(se.sourceIndex, buckets.get(se.sourceIndex)!)
                }

                // Clear raw snapshot data from cache — the store is now the sole owner
                for (const loaded of loadedSources) {
                    const k = keyForSource(loaded)
                    if (cache.snapshotsBySource?.[k]) {
                        delete cache.snapshotsBySource[k].snapshots
                    }
                }
            }

            // whenever we load a set of data, we try to load the next set right away
            actions.loadNextSnapshotSource()
        },

        loadSnapshotsForSourceFailure: async (_, breakpoint) => {
            cache.loadFailureCount = (cache.loadFailureCount ?? 0) + 1
            if (cache.loadFailureCount > 3) {
                return
            }
            await breakpoint(cache.loadFailureCount * 2000)
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
            if (cache.useSnapshotStore && !cache.playerActive) {
                return
            }
            if (values.snapshotsForSourceLoading) {
                return
            }

            await breakpoint(1)

            const sources = values.snapshotSources
            if (!sources?.length) {
                return
            }

            // New store-based path
            if (cache.useSnapshotStore) {
                if (!cache.scheduler || !cache.store) {
                    return
                }
                const batch = cache.scheduler.getNextBatch(cache.store, 10, cache.playbackPosition)
                if (!batch) {
                    actions.maybeStartPolling()
                    return
                }
                const batchSources = batch.sourceIndices.map((i: number) => sources[i]).filter(Boolean)
                if (batchSources.length > 0) {
                    return actions.loadSnapshotsForSource(batchSources)
                }
                actions.maybeStartPolling()
                return
            }

            // Legacy buffer_ahead loading path
            const isSourceLoaded = (source: SessionRecordingSnapshotSource): boolean => {
                const sourceKey = keyForSource(source)
                return !!cache.snapshotsBySource?.[sourceKey]?.sourceLoaded
            }

            const hasBlobV2 = sources.some((s) => s.source === SnapshotSourceType.blob_v2)

            if (hasBlobV2) {
                const nextSourcesToLoad = sources.filter(
                    (s) => s.source !== SnapshotSourceType.file && !isSourceLoaded(s)
                )

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
            (s) => [s.snapshotSourcesLoading, s.snapshotsForSourceLoading, s.snapshotsBySources, s.storeVersion],
            (
                snapshotSourcesLoading: boolean,
                snapshotsForSourceLoading: boolean,
                snapshotsBySources: Record<string, RecordingSnapshot[]>
            ): boolean => {
                if (cache.useSnapshotStore && cache.store) {
                    return (
                        cache.store.getAllLoadedSnapshots().length === 0 &&
                        (snapshotSourcesLoading || snapshotsForSourceLoading)
                    )
                }
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
                // Store path doesn't use snapshotsBySources — return stable reference
                // to avoid the shallow copy on every batch load.
                if (cache.useSnapshotStore) {
                    cache.stableEmptyBySources = cache.stableEmptyBySources || {}
                    return cache.stableEmptyBySources
                }

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
                if (cache.useSnapshotStore && cache.store) {
                    return cache.store.allLoaded
                }
                return snapshotSources.every((source) => {
                    const sourceKey = keyForSource(source)
                    return cache.snapshotsBySource?.[sourceKey]?.sourceLoaded
                })
            },
        ],

        storeVersion: [
            (s) => [s.snapshotsBySourceSuccessCount, s.snapshotSources],
            (): number => {
                return cache.store?.version ?? 0
            },
        ],

        snapshotStore: [
            (s) => [s.storeVersion],
            (): SnapshotStore | null => {
                return cache.store ?? null
            },
        ],

        sourceLoadingStates: [
            (s) => [s.storeVersion],
            (): SourceLoadingState[] => {
                return cache.store?.getSourceStates() ?? []
            },
        ],

        isWaitingForPlayableFullSnapshot: [
            (s) => [s.storeVersion],
            (): boolean => {
                if (!cache.useSnapshotStore || !cache.scheduler || !cache.store) {
                    return false
                }
                const mode = cache.scheduler.currentMode
                if (mode.kind !== 'seek') {
                    return false
                }
                return !cache.store.canPlayAt(mode.targetTimestamp)
            },
        ],
    })),
    afterMount(({ actions, cache, values }) => {
        // Initialize store + scheduler when flag is on
        const useStore = values.featureFlags[FEATURE_FLAGS.REPLAY_SNAPSHOT_STORE] === 'test'
        cache.useSnapshotStore = useStore
        cache.playerActive = true
        if (useStore) {
            cache.store = new SnapshotStore()
            cache.scheduler = new LoadingScheduler()
        }

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
        cache.useSnapshotStore = false
        cache.snapshotsBySource = undefined
        cache.previousSourceKeys = undefined
        cache.lastSourcesChangeTime = undefined
        cache.store = undefined
        cache.scheduler = undefined
        cache.playbackPosition = undefined
        cache.loadFailureCount = undefined
    }),
])
