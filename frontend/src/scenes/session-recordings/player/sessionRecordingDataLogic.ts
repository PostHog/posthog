import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import {
    AvailableFeature,
    EncodedRecordingSnapshot,
    PerformanceEvent,
    RecordingEventsFilters,
    RecordingEventType,
    RecordingReportLoadTimes,
    RecordingSegment,
    RecordingSnapshot,
    SessionPlayerData,
    SessionPlayerSnapshotData,
    SessionRecordingId,
    SessionRecordingSnapshotResponse,
    SessionRecordingSnapshotSource,
    SessionRecordingType,
    SessionRecordingUsageType,
} from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { eventWithTime } from '@rrweb/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import type { sessionRecordingDataLogicType } from './sessionRecordingDataLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { chainToElements } from 'lib/utils/elements-chain'
import { captureException } from '@sentry/react'
import { createSegments, mapSnapshotsToWindowId } from './utils/segmenter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import posthog from 'posthog-js'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
const BUFFER_MS = 60000 // +- before and after start and end of a recording to query for.

const parseEncodedSnapshots = (items: (EncodedRecordingSnapshot | string)[]): RecordingSnapshot[] => {
    const snapshots: RecordingSnapshot[] = items.flatMap((l) => {
        try {
            const snapshotLine = typeof l === 'string' ? (JSON.parse(l) as EncodedRecordingSnapshot) : l
            const snapshotData = snapshotLine['data']

            return snapshotData.map((d: any) => ({
                windowId: snapshotLine['window_id'],
                ...d,
            }))
        } catch (e) {
            captureException(e)
            return []
        }
    })

    return snapshots
}

export const prepareRecordingSnapshots = (
    newSnapshots?: RecordingSnapshot[],
    existingSnapshots?: RecordingSnapshot[]
): RecordingSnapshot[] => {
    const seenHashes: Record<string, (RecordingSnapshot | string)[]> = {}

    const prepared = (newSnapshots || [])
        .concat(existingSnapshots ? existingSnapshots ?? [] : [])
        .filter((snapshot) => {
            // For a multitude of reasons, there can be duplicate snapshots in the same recording.
            // We can deduplicate by filtering out snapshots with the same timestamp and delay value (this is quite unique as a pairing)
            const key = `${snapshot.timestamp}-${snapshot.delay}`

            if (!seenHashes[key]) {
                seenHashes[key] = [snapshot]
            } else {
                // If we are looking at an identical event time, we stringify the original snapshot if not already stringified,
                // Then stringify the new snapshot and compare the two. If it is the same, we can ignore it.
                seenHashes[key][0] =
                    typeof seenHashes[key][0] === 'string' ? seenHashes[key][0] : JSON.stringify(seenHashes[key][0])
                const newSnapshot = JSON.stringify(snapshot)
                if (seenHashes[key][0] === newSnapshot) {
                    return false
                }
                seenHashes[key].push(snapshot)
            }

            return true
        })
        .sort((a, b) => a.timestamp - b.timestamp)

    return prepared
}

export const convertSnapshotsByWindowId = (snapshotsByWindowId: {
    [key: string]: eventWithTime[]
}): RecordingSnapshot[] => {
    return Object.entries(snapshotsByWindowId).flatMap(([windowId, snapshots]) => {
        return snapshots.map((snapshot) => ({
            ...snapshot,
            windowId,
        }))
    })
}

// Until we change the API to return a simple list of snapshots, we need to convert this ourselves
export const convertSnapshotsResponse = (
    snapshotsByWindowId: { [key: string]: eventWithTime[] },
    existingSnapshots?: RecordingSnapshot[]
): RecordingSnapshot[] => {
    return prepareRecordingSnapshots(convertSnapshotsByWindowId(snapshotsByWindowId), existingSnapshots)
}

const generateRecordingReportDurations = (
    cache: Record<string, any>,
    values: Record<string, any>
): RecordingReportLoadTimes => {
    // TODO: This anytyping is super hard to manage - we should either type it or move it to a selector.
    return {
        metadata: {
            size: values.segments.length,
            duration: Math.round(performance.now() - cache.metaStartTime),
        },
        snapshots: {
            size: (values.sessionPlayerSnapshotData?.segments ?? []).length,
            duration: Math.round(performance.now() - cache.snapshotsStartTime),
        },
        events: {
            size: values.sessionEventsData?.length ?? 0,
            duration: Math.round(performance.now() - cache.eventsStartTime),
        },
        performanceEvents: {
            size: values.performanceEvents?.length ?? 0,
            duration: Math.round(performance.now() - cache.performanceEventsStartTime),
        },
        firstPaint: cache.firstPaintDurationRow,
    }
}

export interface SessionRecordingDataLogicProps {
    sessionRecordingId: SessionRecordingId
    recordingStartTime?: string
}

export const sessionRecordingDataLogic = kea<sessionRecordingDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionRecordingDataLogic', key]),
    props({} as SessionRecordingDataLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect({
        logic: [eventUsageLogic],
        values: [teamLogic, ['currentTeamId'], userLogic, ['hasAvailableFeature'], featureFlagLogic, ['featureFlags']],
    }),
    defaults({
        sessionPlayerMetaData: null as SessionRecordingType | null,
    }),
    actions({
        setFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
        loadRecording: (full: boolean = false) => ({ full }),
        loadRecordingMeta: true,
        addDiffToRecordingMetaPinnedCount: (diffCount: number) => ({ diffCount }),
        loadRecordingSnapshots: (nextUrl?: string) => ({ nextUrl }),
        loadRecordingSnapshotsV2: (source?: SessionRecordingSnapshotSource) => ({ source }),
        loadEvents: true,
        loadFullEventData: (event: RecordingEventType) => ({ event }),
        loadPerformanceEvents: (nextUrl?: string) => ({ nextUrl }),
        reportViewed: true,
        reportUsageIfFullyLoaded: true,
    }),
    reducers(() => ({
        fullLoad: [
            false as boolean,
            {
                loadRecording: (_, { full }) => full,
            },
        ],
        filters: [
            {} as Partial<RecordingEventsFilters>,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        chunkPaginationIndex: [
            0,
            {
                loadRecordingSnapshotsSuccess: (state) => state + 1,
            },
        ],
        loadedFromBlobStorage: [
            false as boolean,
            {
                loadRecordingSnapshotsV2Success: () => true,
            },
        ],
        isNotFound: [
            false as boolean,
            {
                loadRecordingMeta: () => false,
                loadRecordingMetaSuccess: () => false,
                loadRecordingMetaFailure: () => true,
            },
        ],
    })),
    listeners(({ values, actions, cache }) => ({
        loadRecording: ({ full }) => {
            // If we don't have metadata then we load that first, which will trigger this again
            if (!values.sessionPlayerMetaData) {
                actions.loadRecordingMeta()
                return
            }

            if (!full) {
                return
            }

            if (!values.sessionPlayerSnapshotData?.snapshots) {
                if (values.featureFlags[FEATURE_FLAGS.SESSION_RECORDING_BLOB_REPLAY]) {
                    actions.loadRecordingSnapshotsV2()
                } else {
                    actions.loadRecordingSnapshots()
                }
            }
            actions.loadEvents()
            actions.loadPerformanceEvents()
        },
        loadRecordingMetaSuccess: () => {
            if (values.fullLoad) {
                actions.loadRecording(true)
            }
        },
        loadRecordingSnapshotsV2Success: () => {
            const { snapshots, sources } = values.sessionPlayerSnapshotData ?? {}
            if (snapshots && !snapshots.length && sources?.length === 1) {
                // We got the snapshot response for realtime, and it was empty, so we fall back to the old API
                // Until we migrate over we need to fall back to the old API if the new one returns no snapshots
                actions.loadRecordingSnapshots()
                return
            }

            const nextSourceToLoad = sources?.find((s) => !s.loaded)

            if (nextSourceToLoad) {
                actions.loadRecordingSnapshotsV2(nextSourceToLoad)
            } else {
                actions.reportUsageIfFullyLoaded()
            }
        },
        loadRecordingSnapshotsSuccess: () => {
            if (!!values.sessionPlayerSnapshotData?.next) {
                actions.loadRecordingSnapshots(values.sessionPlayerSnapshotData?.next)
            } else {
                actions.reportUsageIfFullyLoaded()
            }
            if (values.chunkPaginationIndex === 1 || values.loadedFromBlobStorage) {
                // Not always accurate that recording is playable after first chunk is loaded, but good guesstimate for now
                // when loading from blob storage by the time this is hit the chunkPaginationIndex is already > 1
                // when loading from the API the chunkPaginationIndex is 1 for the first success that reaches this point
                cache.firstPaintDurationRow = {
                    size: (values.sessionPlayerSnapshotData?.snapshots ?? []).length,
                    duration: Math.round(performance.now() - cache.snapshotsStartTime),
                }

                actions.reportViewed()
            }
        },
        loadEventsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },
        loadPerformanceEventsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },
        reportUsageIfFullyLoaded: () => {
            if (values.fullyLoaded) {
                eventUsageLogic.actions.reportRecording(
                    values.sessionPlayerData,
                    generateRecordingReportDurations(cache, values),
                    SessionRecordingUsageType.LOADED,
                    0
                )
                // Reset cache now that final usage report has been sent
                cache.metaStartTime = null
                cache.snapshotsStartTime = null
                cache.eventsStartTime = null
                cache.performanceEventsStartTime = null
                cache.firstPaintDurationRow = null
            }
        },
        reportViewed: async (_, breakpoint) => {
            const durations = generateRecordingReportDurations(cache, values)

            await breakpoint()
            // Triggered on first paint
            eventUsageLogic.actions.reportRecording(
                values.sessionPlayerData,
                durations,
                SessionRecordingUsageType.VIEWED,
                0,
                values.loadedFromBlobStorage
            )
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportRecording(
                values.sessionPlayerData,
                durations,
                SessionRecordingUsageType.ANALYZED,
                10,
                values.loadedFromBlobStorage
            )
        },
    })),
    loaders(({ values, props, cache }) => ({
        sessionPlayerMetaData: {
            loadRecordingMeta: async (_, breakpoint) => {
                cache.metaStartTime = performance.now()
                if (!props.sessionRecordingId) {
                    return null
                }
                const params = toParams({
                    save_view: true,
                    recording_start_time: props.recordingStartTime,
                })
                const response = await api.recordings.get(props.sessionRecordingId, params)
                breakpoint()

                return response
            },
            addDiffToRecordingMetaPinnedCount: ({ diffCount }) => {
                if (!values.sessionPlayerMetaData) {
                    return null
                }

                return {
                    ...values.sessionPlayerMetaData,
                    pinned_count: Math.max(values.sessionPlayerMetaData.pinned_count ?? 0 + diffCount, 0),
                }
            },
        },
        sessionPlayerSnapshotData: [
            null as SessionPlayerSnapshotData | null,
            {
                loadRecordingSnapshots: async ({ nextUrl }, breakpoint): Promise<SessionPlayerSnapshotData | null> => {
                    cache.snapshotsStartTime = performance.now()

                    if (!props.sessionRecordingId) {
                        return values.sessionPlayerSnapshotData
                    }
                    await breakpoint(1)

                    const params = toParams({
                        recording_start_time: props.recordingStartTime,
                    })
                    const apiUrl =
                        nextUrl ||
                        `api/projects/${values.currentTeamId}/session_recordings/${props.sessionRecordingId}/snapshots?${params}`
                    const response: SessionRecordingSnapshotResponse = await api.get(apiUrl)
                    breakpoint()

                    // NOTE: This might seem backwards as we translate the snapshotsByWindowId to an array and then derive it again later but
                    // this is for future support of the API that will return them as a simple array

                    if (response.snapshot_data_by_window_id) {
                        const snapshots = convertSnapshotsResponse(
                            response.snapshot_data_by_window_id,
                            nextUrl ? values.sessionPlayerSnapshotData?.snapshots ?? [] : []
                        )

                        posthog.capture('recording_snapshot_loaded', {
                            source: 'clickhouse',
                        })

                        return {
                            snapshots,
                            next: response.next,
                        }
                    } else {
                        throw new Error('Invalid response from snapshots API')
                    }
                },

                loadRecordingSnapshotsV2: async ({ source }, breakpoint): Promise<SessionPlayerSnapshotData | null> => {
                    if (!props.sessionRecordingId) {
                        return values.sessionPlayerSnapshotData
                    }

                    cache.snapshotsStartTime = performance.now()

                    const data: SessionPlayerSnapshotData = {
                        ...(values.sessionPlayerSnapshotData || {}),
                    }

                    await breakpoint(1)

                    if (source?.source === 'blob') {
                        if (!source.blob_key) {
                            throw new Error('Missing key')
                        }
                        const encodedResponse = await api.recordings.getBlobSnapshots(
                            props.sessionRecordingId,
                            source.blob_key
                        )
                        data.snapshots = prepareRecordingSnapshots(
                            parseEncodedSnapshots(encodedResponse),
                            values.sessionPlayerSnapshotData?.snapshots ?? []
                        )
                    } else {
                        const params = toParams({
                            source: source?.source,
                            key: source?.blob_key,
                            version: '2',
                        })
                        const response = await api.recordings.listSnapshots(props.sessionRecordingId, params)
                        if (response.snapshots) {
                            data.snapshots = prepareRecordingSnapshots(
                                parseEncodedSnapshots(response.snapshots),
                                values.sessionPlayerSnapshotData?.snapshots ?? []
                            )
                        }

                        if (response.sources) {
                            data.sources = response.sources
                        }
                    }

                    if (source) {
                        source.loaded = true

                        posthog.capture('recording_snapshot_loaded', {
                            source: source.source,
                        })
                    }

                    return data
                },
            },
        ],
        sessionEventsData: [
            null as null | RecordingEventType[],
            {
                loadEvents: async () => {
                    const { start, end, person } = values.sessionPlayerData

                    if (!person || !start || !end) {
                        return null
                    }

                    const [sessionEvents, relatedEvents]: any[] = await Promise.all(
                        [
                            {
                                key: '$session_id',
                                value: [props.sessionRecordingId],
                                operator: 'exact',
                                type: 'event',
                            },
                            {
                                key: '$session_id',
                                value: '',
                                operator: 'exact',
                                type: 'event',
                            },
                        ].map((properties) =>
                            api.query({
                                kind: 'EventsQuery',
                                // NOTE: Be careful adding fields here. We want to keep the payload as small as possible to load all events quickly
                                select: [
                                    'uuid',
                                    'event',
                                    'timestamp',
                                    'elements_chain',
                                    'properties.$window_id',
                                    'properties.$current_url',
                                    'properties.$event_type',
                                ],
                                orderBy: ['timestamp ASC'],
                                limit: 1000000,
                                personId: person.id,
                                after: start.subtract(BUFFER_MS, 'ms').format(),
                                before: end.add(BUFFER_MS, 'ms').format(),
                                properties: [properties],
                            })
                        )
                    )

                    const minimalEvents = [...sessionEvents.results, ...relatedEvents.results].map(
                        (event: any): RecordingEventType => {
                            const currentUrl = event[5]
                            // We use the pathname to simplify the UI - we build it here instead of fetching it to keep data usage small
                            let pathname = undefined
                            try {
                                pathname = event[5] ? new URL(event[5]).pathname : undefined
                            } catch {}

                            return {
                                id: event[0],
                                event: event[1],
                                timestamp: event[2],
                                elements: chainToElements(event[3]),
                                properties: {
                                    $window_id: event[4],
                                    $current_url: currentUrl,
                                    $event_type: event[6],
                                    $pathname: pathname,
                                },
                                playerTime: +dayjs(event[2]) - +start,
                                fullyLoaded: false,
                            }
                        }
                    )

                    return minimalEvents
                },

                loadFullEventData: async ({ event }) => {
                    const existingEvent = values.sessionEventsData?.find((x) => x.id === event.id)
                    if (!existingEvent || existingEvent.fullyLoaded) {
                        return values.sessionEventsData
                    }

                    const { person } = values.sessionPlayerData

                    // TODO: Move this to an optimised HogQL query when available...
                    try {
                        const res: any = await api.query({
                            kind: 'EventsQuery',
                            select: ['properties', 'timestamp'],
                            orderBy: ['timestamp ASC'],
                            limit: 100,
                            personId: person?.id,
                            after: dayjs(event.timestamp).subtract(1000, 'ms').format(),
                            before: dayjs(event.timestamp).add(1000, 'ms').format(),
                            event: existingEvent.event,
                        })

                        const result = res.results.find((x: any) => x[1] === event.timestamp)

                        if (result) {
                            existingEvent.properties = JSON.parse(result[0])
                            existingEvent.fullyLoaded = true
                        }
                    } catch (e) {
                        // NOTE: This is not ideal but should happen so rarely that it is tolerable.
                        existingEvent.fullyLoaded = true
                        captureException(e)
                    }

                    return values.sessionEventsData
                },
            },
        ],

        performanceEvents: [
            null as null | PerformanceEvent[],
            {
                loadPerformanceEvents: async ({}, breakpoint) => {
                    const { start, end } = values.sessionPlayerData

                    if (
                        !props.sessionRecordingId ||
                        !start ||
                        !end ||
                        !values.hasAvailableFeature(AvailableFeature.RECORDINGS_PERFORMANCE)
                    ) {
                        return []
                    }

                    cache.performanceEventsStartTime = performance.now()

                    await breakpoint(1)

                    // Use `nextUrl` if there is a `next` url to fetch
                    const response = await api.performanceEvents.list({
                        session_id: props.sessionRecordingId,
                        date_from: start.subtract(BUFFER_MS, 'ms').format(),
                        date_to: end.add(BUFFER_MS, 'ms').format(),
                    })

                    breakpoint()

                    return response.results
                },
            },
        ],
    })),
    selectors({
        sessionPlayerData: [
            (s) => [
                s.sessionPlayerMetaData,
                s.snapshotsByWindowId,
                s.segments,
                s.bufferedToTime,
                s.start,
                s.end,
                s.durationMs,
                s.fullyLoaded,
            ],
            (
                meta,
                snapshotsByWindowId,
                segments,
                bufferedToTime,
                start,
                end,
                durationMs,
                fullyLoaded
            ): SessionPlayerData => ({
                pinnedCount: meta?.pinned_count ?? 0,
                person: meta?.person ?? null,
                start,
                end,
                durationMs,
                snapshotsByWindowId,
                segments,
                bufferedToTime,
                fullyLoaded,
            }),
        ],

        fullyLoaded: [
            (s) => [
                s.sessionPlayerSnapshotData,
                s.sessionPlayerMetaDataLoading,
                s.sessionPlayerSnapshotDataLoading,
                s.sessionEventsDataLoading,
                s.hasAvailableFeature,
                s.performanceEventsLoading,
            ],
            (
                sessionPlayerSnapshotData,
                sessionPlayerMetaDataLoading,
                sessionPlayerSnapshotDataLoading,
                sessionEventsDataLoading,
                hasAvailableFeature,
                performanceEventsLoading
            ): boolean => {
                return (
                    !!sessionPlayerSnapshotData?.snapshots?.length &&
                    !sessionPlayerMetaDataLoading &&
                    !sessionPlayerSnapshotDataLoading &&
                    !sessionEventsDataLoading &&
                    (hasAvailableFeature(AvailableFeature.RECORDINGS_PERFORMANCE) ? !performanceEventsLoading : true)
                )
            },
        ],

        start: [
            (s) => [s.sessionPlayerMetaData],
            (meta): Dayjs | undefined => {
                return meta?.start_time ? dayjs(meta.start_time) : undefined
            },
        ],

        end: [
            (s) => [s.sessionPlayerMetaData, s.sessionPlayerSnapshotData],
            (meta, sessionPlayerSnapshotData): Dayjs | undefined => {
                // NOTE: We might end up with more snapshots than we knew about when we started the recording so we
                // either use the metadata end point or the last snapshot, whichever is later.
                const end = meta?.end_time ? dayjs(meta.end_time) : undefined
                const lastEvent = sessionPlayerSnapshotData?.snapshots?.slice(-1)[0]

                return lastEvent?.timestamp && lastEvent.timestamp > +(end ?? 0) ? dayjs(lastEvent.timestamp) : end
            },
        ],

        durationMs: [
            (s) => [s.start, s.end],
            (start, end): number => {
                return end?.diff(start) ?? 0
            },
        ],

        segments: [
            (s) => [s.sessionPlayerSnapshotData, s.start, s.end],
            (sessionPlayerSnapshotData, start, end): RecordingSegment[] => {
                return createSegments(sessionPlayerSnapshotData?.snapshots || [], start, end)
            },
        ],

        snapshotsByWindowId: [
            (s) => [s.sessionPlayerSnapshotData],
            (sessionPlayerSnapshotData): Record<string, eventWithTime[]> => {
                return mapSnapshotsToWindowId(sessionPlayerSnapshotData?.snapshots || [])
            },
        ],

        bufferedToTime: [
            (s) => [s.segments],
            (segments): number | null => {
                if (!segments.length) {
                    return null
                }

                const startTime = segments[0].startTimestamp
                const lastSegment = segments[segments.length - 1]

                if (lastSegment.kind === 'buffer') {
                    return lastSegment.startTimestamp - startTime
                }

                return lastSegment.endTimestamp - startTime
            },
        ],

        windowIds: [
            (s) => [s.snapshotsByWindowId],
            (snapshotsByWindowId) => {
                return Object.keys(snapshotsByWindowId)
            },
        ],
    }),
])
