import { actions, afterMount, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import {
    AvailableFeature,
    PerformanceEvent,
    RecordingEventsFilters,
    RecordingEventType,
    RecordingReportLoadTimes,
    RecordingSegment,
    RecordingSnapshot,
    SessionPlayerData,
    SessionPlayerSnapshotData,
    SessionRecordingId,
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
import { decompressSync, strFromU8 } from 'fflate'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
const BUFFER_MS = 60000 // +- before and after start and end of a recording to query for.

export const prepareRecordingSnapshots = (
    newSnapshots?: RecordingSnapshot[],
    existingSnapshots?: RecordingSnapshot[]
): RecordingSnapshot[] => {
    return (newSnapshots || [])
        .concat(existingSnapshots ? existingSnapshots ?? [] : [])
        .sort((a, b) => a.timestamp - b.timestamp)
}

// Until we change the API to return a simple list of snapshots, we need to convert this ourselves
export const convertSnapshotsResponse = (
    snapshotsByWindowId: { [key: string]: eventWithTime[] },
    existingSnapshots?: RecordingSnapshot[]
): RecordingSnapshot[] => {
    const snapshots: RecordingSnapshot[] = Object.entries(snapshotsByWindowId).flatMap(([windowId, snapshots]) => {
        return snapshots.map((snapshot) => ({
            ...snapshot,
            windowId,
        }))
    })

    return prepareRecordingSnapshots(snapshots, existingSnapshots)
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

async function makeSnapshotsAPICall({
    breakpoint,
    nextUrl,
    recordingStartTime,
    blobLoadingEnabled,
    currentSnapshotData,
    currentTeamId,
    sessionRecordingId,
}: {
    breakpoint: (() => void) & ((ms: number) => Promise<void>)
    nextUrl: string | undefined
    recordingStartTime: string | undefined
    blobLoadingEnabled: boolean
    currentSnapshotData: SessionPlayerSnapshotData | null
    currentTeamId: number | null
    sessionRecordingId: string | undefined
}): Promise<SessionPlayerSnapshotData> {
    const params = toParams({
        recording_start_time: recordingStartTime,
        blob_loading_enabled: blobLoadingEnabled,
    })
    const apiUrl =
        nextUrl || `api/projects/${currentTeamId}/session_recordings/${sessionRecordingId}/snapshots?${params}`
    const response = await api.get(apiUrl)
    breakpoint()

    // NOTE: This might seem backwards as we translate the snapshotsByWindowId to an array and then derive it again later but
    // this is for future support of the API that will return them as a simple array

    if (!response.blob_keys) {
        const snapshots = convertSnapshotsResponse(
            response.snapshot_data_by_window_id,
            nextUrl ? currentSnapshotData?.snapshots ?? [] : []
        )
        return {
            snapshots,
            next: response.next,
        }
    } else {
        return {
            snapshots: [],
            blob_keys: response.blob_keys,
        }
    }
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
        loadEntireRecording: true,
        loadRecordingMeta: true,
        addDiffToRecordingMetaPinnedCount: (diffCount: number) => ({ diffCount }),
        loadRecordingSnapshots: (nextUrl?: string) => ({ nextUrl }),
        loadEvents: true,
        loadFullEventData: (event: RecordingEventType) => ({ event }),
        loadPerformanceEvents: (nextUrl?: string) => ({ nextUrl }),
        reportViewed: true,
        reportUsageIfFullyLoaded: true,
    }),
    reducers(() => ({
        filters: [
            {} as Partial<RecordingEventsFilters>,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        sessionRecordingId: [
            null as SessionRecordingId | null,
            {
                loadRecording: (_, { sessionRecordingId }) => sessionRecordingId ?? null,
            },
        ],
        chunkPaginationIndex: [
            0,
            {
                loadRecordingSnapshotsSuccess: (state) => state + 1,
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
    listeners(({ values, props, actions, cache }) => ({
        loadEntireRecording: () => {
            actions.loadRecordingMeta()
        },
        loadRecordingMetaSuccess: () => {
            if (!values.sessionPlayerSnapshotData?.snapshots) {
                actions.loadRecordingSnapshots()
            }
            actions.loadEvents()
            actions.loadPerformanceEvents()
        },
        loadRecordingBlobSnapshotsSuccess: () => {
            if (values.sessionPlayerSnapshotData?.blob_keys?.length) {
                actions.loadRecordingBlobSnapshots(null)
            } else {
                actions.loadRecordingSnapshotsSuccess(values.sessionPlayerSnapshotData)
            }
        },
        loadRecordingSnapshotsSuccess: () => {
            if (values.sessionPlayerSnapshotData?.blob_keys?.length) {
                actions.loadRecordingBlobSnapshots(null)
                return
            } else if (!!values.sessionPlayerSnapshotData?.next) {
                actions.loadRecordingSnapshots(values.sessionPlayerSnapshotData?.next)
            } else {
                actions.reportUsageIfFullyLoaded()
            }
            // Not always accurate that recording is playable after first chunk is loaded, but good guesstimate for now
            if (values.chunkPaginationIndex === 1) {
                cache.firstPaintDurationRow = {
                    size: (values.sessionPlayerSnapshotData?.snapshots ?? []).length,
                    duration: Math.round(performance.now() - cache.snapshotsStartTime),
                }

                actions.reportViewed()
            }

            if (!values.sessionPlayerSnapshotData?.next) {
                // this is a short term mechanism to compare blob and api loaded snapshot data
                ;(window as any).PH_SESSION_REPLAY = {
                    compare: async () => {
                        console.group('comparing session for: ', props.sessionRecordingId)
                        if (!values.featureFlags[FEATURE_FLAGS.SESSION_RECORDING_BLOB_REPLAY]) {
                            console.error(
                                'FOR SIMPLICITY THIS MECHANISM ASSUMES YOU HAVE THE BLOB STORAGE FLAG ENABLED'
                            )
                            return false
                        }
                        if (!values.sessionPlayerSnapshotData?.snapshots.length) {
                            console.log('There are no current values **from blob storage**')
                        }
                        const fakePoint = (): Promise<void> => Promise.resolve()
                        let comparisonData = await makeSnapshotsAPICall({
                            breakpoint: fakePoint,
                            nextUrl: undefined,
                            recordingStartTime: props.recordingStartTime,
                            blobLoadingEnabled: false,
                            currentSnapshotData: null,
                            currentTeamId: values.currentTeamId,
                            sessionRecordingId: props.sessionRecordingId,
                        })

                        while (comparisonData.next) {
                            comparisonData = await makeSnapshotsAPICall({
                                breakpoint: fakePoint,
                                nextUrl: comparisonData.next,
                                recordingStartTime: props.recordingStartTime,
                                blobLoadingEnabled: false,
                                currentSnapshotData: comparisonData,
                                currentTeamId: values.currentTeamId,
                                sessionRecordingId: props.sessionRecordingId,
                            })
                        }
                        console.log('finished loading comparison data')
                        console.log('now we have: ', {
                            fromBlobStorage: values.sessionPlayerSnapshotData?.snapshots,
                            fromAPI: comparisonData?.snapshots,
                        })

                        console.log(
                            'blob storage returned ',
                            values.sessionPlayerSnapshotData?.snapshots?.length,
                            ' snapshots'
                        )
                        console.log('api returned ', comparisonData?.snapshots?.length, ' snapshots')

                        const timestampsMatch = values.sessionPlayerSnapshotData?.snapshots?.every(
                            (snapshot, index) => {
                                const comparisonSnapshot = comparisonData?.snapshots?.[index]
                                if (!comparisonSnapshot) {
                                    return false
                                }
                                return snapshot.timestamp === comparisonSnapshot.timestamp
                            }
                        )

                        if (values.sessionPlayerSnapshotData?.snapshots?.length === comparisonData?.snapshots?.length) {
                            if (timestampsMatch) {
                                console.log('🎉 storage and api have the same timestamps ✅')
                            } else {
                                console.error(
                                    '🧨 storage and api snapshots are the same length but have different timestamps'
                                )
                            }
                        } else {
                            if (timestampsMatch) {
                                console.error(
                                    '⚠️ storage and api have the same timestamps but different lengths. If this is a recent recording then the ingester probably has not flushed the whole thing yet'
                                )
                            } else {
                                console.error('🧨 storage and api have different lengths and different timestamps')
                            }
                        }

                        console.groupEnd()
                    },
                }
            }
        },
        loadEventsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },
        loadPerformanceEventsSuccess: () => {
            actions.reportUsageIfFullyLoaded()
        },
        reportUsageIfFullyLoaded: () => {
            const partsOfRecordingAreStillLoading =
                values.sessionPlayerMetaDataLoading ||
                values.sessionPlayerSnapshotDataLoading ||
                values.sessionEventsDataLoading ||
                (values.hasAvailableFeature(AvailableFeature.RECORDINGS_PERFORMANCE)
                    ? values.performanceEventsLoading
                    : false)
            if (!partsOfRecordingAreStillLoading) {
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
                0
            )
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportRecording(
                values.sessionPlayerData,
                durations,
                SessionRecordingUsageType.ANALYZED,
                10
            )
        },
    })),
    loaders(({ values, props, cache, actions }) => ({
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

                if (response.snapshot_data_by_window_id) {
                    const snapshots = convertSnapshotsResponse(response.snapshot_data_by_window_id)
                    // When loaded from S3 the snapshots are already present
                    actions.loadRecordingSnapshotsSuccess({
                        snapshots,
                    })
                }

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
                loadRecordingBlobSnapshots: async (_, breakpoint): Promise<SessionPlayerSnapshotData | null> => {
                    const snapshotDataClone = { ...values.sessionPlayerSnapshotData } as SessionPlayerSnapshotData

                    if (!snapshotDataClone?.blob_keys?.length) {
                        // only call this loader action when there are blob_keys to load
                        return snapshotDataClone
                    }

                    await breakpoint(1)

                    const blob_key = snapshotDataClone.blob_keys.shift()

                    const response = await api.getResponse(
                        `api/projects/${values.currentTeamId}/session_recordings/${props.sessionRecordingId}/snapshot_file/?blob_key=${blob_key}`
                    )
                    breakpoint()

                    const contentBuffer = new Uint8Array(await response.arrayBuffer())
                    const jsonLines = strFromU8(decompressSync(contentBuffer)).trim().split('\n')
                    const snapshots: RecordingSnapshot[] = jsonLines.flatMap((l) => {
                        const snapshotLine = JSON.parse(l)
                        const snapshotData = JSON.parse(snapshotLine['data'])

                        return snapshotData.map((d: any) => ({
                            windowId: snapshotLine['window_id'],
                            ...d,
                        }))
                    })

                    return {
                        blob_keys: snapshotDataClone.blob_keys,
                        snapshots: prepareRecordingSnapshots(snapshots, snapshotDataClone.snapshots),
                    }
                },
                loadRecordingSnapshots: async ({ nextUrl }, breakpoint): Promise<SessionPlayerSnapshotData | null> => {
                    cache.snapshotsStartTime = performance.now()

                    if (!props.sessionRecordingId) {
                        return values.sessionPlayerSnapshotData
                    }
                    await breakpoint(1)

                    return await makeSnapshotsAPICall({
                        breakpoint,
                        nextUrl,
                        recordingStartTime: props.recordingStartTime,
                        blobLoadingEnabled: !!values.featureFlags[FEATURE_FLAGS.SESSION_RECORDING_BLOB_REPLAY],
                        currentSnapshotData: values.sessionPlayerSnapshotData,
                        currentTeamId: values.currentTeamId,
                        sessionRecordingId: props.sessionRecordingId,
                    })
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

                    // TODO: Move this to an optimised HoqQL query when available...
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
            ],
            (meta, snapshotsByWindowId, segments, bufferedToTime, start, end, durationMs): SessionPlayerData => ({
                pinnedCount: meta?.pinned_count ?? 0,
                person: meta?.person ?? null,
                start,
                end,
                durationMs,
                snapshotsByWindowId,
                segments,
                bufferedToTime,
            }),
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
    afterMount(({ props, actions }) => {
        if (props.sessionRecordingId) {
            actions.loadEntireRecording()
        }
    }),
])
