import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import '@posthog/rrweb-types'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { parseEncodedSnapshots } from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'
import { SourceKey, keyForSource } from 'scenes/session-recordings/player/snapshot-processing/source-key'

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

export const snapshotDataLogic = kea<snapshotDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'snapshotLogic', key]),
    props({} as SnapshotLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
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
    loaders(({ values, props, cache }) => ({
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

                    const blob_v2 = true
                    const blob_v2_lts = true
                    const response = await api.recordings.listSnapshotSources(
                        props.sessionRecordingId,
                        {
                            blob_v2,
                            blob_v2_lts,
                        },
                        headers
                    )

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

                    if (sources.length > 1) {
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
                    } else {
                        const source = sources[0]

                        if (source.source === SnapshotSourceType.blob) {
                            if (!source.blob_key) {
                                throw new Error('Missing key')
                            }
                            params = { blob_key: source.blob_key, source: 'blob' }
                        } else if (source.source === SnapshotSourceType.blob_v2) {
                            params = { source: 'blob_v2', blob_key: source.blob_key }
                        } else if (source.source === SnapshotSourceType.file) {
                            // no need to load a file source, it is already loaded
                            return { source }
                        } else {
                            throw new Error(`Unsupported source: ${source.source}`)
                        }
                    }

                    await breakpoint(1)

                    const headers: Record<string, string> = {}
                    if (props.accessToken) {
                        headers.Authorization = `Bearer ${props.accessToken}`
                    }

                    const clientSideDecompression = values.featureFlags[FEATURE_FLAGS.REPLAY_CLIENT_SIDE_DECOMPRESSION]
                    if (clientSideDecompression) {
                        params = { ...params, decompress: false }
                    }

                    const response = await api.recordings.getSnapshots(props.sessionRecordingId, params, headers)

                    // sorting is very cheap for already sorted lists
                    const parsedSnapshots = (await parseEncodedSnapshots(response, props.sessionRecordingId)).sort(
                        (a, b) => a.timestamp - b.timestamp
                    )
                    // we store the data in the cache because we want to avoid copying this data as much as possible
                    // and kea's immutability means we were copying all the data on every snapshot call
                    cache.snapshotsBySource = cache.snapshotsBySource || {}
                    // it doesn't matter which source we use as the key, since we combine the snapshots anyway
                    cache.snapshotsBySource[keyForSource(sources[0])] = { snapshots: parsedSnapshots }
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
        setSnapshots: ({ snapshots }: { snapshots: RecordingSnapshot[] }) => {
            cache.snapshotsBySource = {
                'file-file': {
                    snapshots: snapshots,
                    source: { source: SnapshotSourceType.file },
                },
            }
            actions.loadSnapshotsForSourceSuccess({
                source: { source: SnapshotSourceType.file },
            })
            actions.loadSnapshotSourcesSuccess([{ source: SnapshotSourceType.file }])
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
            const snapshots = (cache.snapshotsBySource || {})[sourceKey] || []

            if (!snapshots.length && sources?.length === 1 && sources[0].source !== SnapshotSourceType.file) {
                // We got only a single source to load, loaded it successfully, but it had no snapshots.
                posthog.capture('recording_snapshots_v2_empty_response', {
                    source: sources[0],
                })
            }

            // when we're doing progressive loading, the player logic decides when to continue
            if (!values.useProgressiveLoading) {
                // if not then whenever we load a set of data, we try to load the next set right away
                actions.loadNextSnapshotSource()
            }
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
                // we already are
                return
            }

            // when we're progressive loading we'll call this a lot
            // because it's triggered on player tick
            // we want to debounce calls because otherwise
            // particularly early in a recording
            // we end up loading everything
            if (values.useProgressiveLoading) {
                await breakpoint(5)
            }

            // yes this is ugly duplication, but we're going to deprecate v1 and I want it to be clear which is which
            if (values.snapshotSources?.some((s) => s.source === SnapshotSourceType.blob_v2)) {
                const nextSourcesToLoad = values.snapshotSources.filter((s) => {
                    if (s.source === SnapshotSourceType.file) {
                        return false
                    }

                    const sourceKey = keyForSource(s)
                    return !cache.snapshotsBySource?.[sourceKey]?.sourceLoaded
                })

                // Load up to 10 sources at once
                if (nextSourcesToLoad.length > 0) {
                    return actions.loadSnapshotsForSource(nextSourcesToLoad.slice(0, 10))
                }

                actions.maybeStartPolling()
            } else {
                // V1 behavior unchanged
                const nextSourceToLoad = values.snapshotSources?.find((s) => {
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
        useProgressiveLoading: [
            (s) => [s.featureFlags],
            (featureFlags) => {
                return !!featureFlags[FEATURE_FLAGS.REPLAY_PROGRESSIVE_LOADING]
            },
        ],

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
                    cache.snapshotsBySource = { ...cache.snapshotsBySource }
                    cache.snapshotsBySource['_count'] = snapshotsBySourceSuccessCount
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
    }),
])
