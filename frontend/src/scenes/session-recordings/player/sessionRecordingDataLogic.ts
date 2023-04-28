import { actions, afterMount, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import {
    AvailableFeature,
    PerformanceEvent,
    PlayerPosition,
    RecordingEventsFilters,
    RecordingEventType,
    RecordingReportLoadTimes,
    RecordingSegment,
    RecordingSnapshot,
    SessionPlayerData,
    SessionPlayerMetaData,
    SessionPlayerSnapshotData,
    SessionRecordingId,
    SessionRecordingType,
    SessionRecordingUsageType,
} from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { eventWithTime } from '@rrweb/types'
import { dayjs } from 'lib/dayjs'
import type { sessionRecordingDataLogicType } from './sessionRecordingDataLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { chainToElements } from 'lib/utils/elements-chain'
import { captureException } from '@sentry/react'
import { createSegments } from './utils/segmenter'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
const BUFFER_MS = 60000 // +- before and after start and end of a recording to query for.

export const parseMetadataResponse = (recording: SessionRecordingType): SessionPlayerMetaData => {
    const segments: RecordingSegment[] =
        recording.segments?.map((segment): RecordingSegment => {
            const windowStartTime = dayjs(recording.start_and_end_times_by_window_id?.[segment.window_id]?.start_time)
            const segmentStartTime = dayjs(segment.start_time)
            const segmentEndTime = dayjs(segment.end_time)
            const startPlayerPosition: PlayerPosition = {
                windowId: segment.window_id,
                time: segmentStartTime.valueOf() - windowStartTime.valueOf(),
            }
            const endPlayerPosition: PlayerPosition = {
                windowId: segment.window_id,
                time: segmentEndTime.valueOf() - windowStartTime.valueOf(),
            }
            const durationMs = segmentEndTime.valueOf() - segmentStartTime.valueOf()

            return {
                startPlayerPosition,
                endPlayerPosition,
                durationMs,
                startTimeEpochMs: segmentStartTime.valueOf(),
                endTimeEpochMs: segmentEndTime.valueOf(),
                windowId: segment.window_id,
                isActive: segment.is_active,
            }
        }) || []

    return {
        pinnedCount: recording.pinned_count ?? 0,
        durationMs: recording.recording_duration * 1000,
        start: dayjs(recording.start_time),
        end: dayjs(recording.end_time),
        person: recording.person ?? null,

        // TODO: Build these ourselves later
        segments,
    }
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
    // Data can be preloaded (e.g. via browser import)
    sessionRecordingData?: SessionPlayerData
    recordingStartTime?: string
}

export const sessionRecordingDataLogic = kea<sessionRecordingDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionRecordingDataLogic', key]),
    props({} as SessionRecordingDataLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect({
        logic: [eventUsageLogic],
        values: [teamLogic, ['currentTeamId'], userLogic, ['hasAvailableFeature']],
    }),
    defaults({
        sessionPlayerMetaData: {
            person: null,
            pinnedCount: 0,
            durationMs: 0,
            start: dayjs(),
            end: dayjs(),
            segments: [],
        } as SessionPlayerMetaData,
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
    listeners(({ values, actions, cache }) => ({
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
        loadRecordingSnapshotsSuccess: () => {
            // If there is more data to poll for load the next batch.
            // This will keep calling loadRecording until `next` is empty.
            if (!!values.sessionPlayerSnapshotData?.next) {
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
    loaders(({ values, props, cache }) => ({
        sessionPlayerMetaData: {
            loadRecordingMeta: async (_, breakpoint) => {
                cache.metaStartTime = performance.now()
                if (!props.sessionRecordingId) {
                    return values.sessionPlayerMetaData
                }
                const params = toParams({
                    save_view: true,
                    recording_start_time: props.recordingStartTime,
                })
                const response = await api.recordings.get(props.sessionRecordingId, params)

                const metadata = parseMetadataResponse(response)
                breakpoint()

                if (response.snapshot_data_by_window_id) {
                    // When loaded from S3 the snapshots are already present
                    // TODO: THIS
                    // actions.loadRecordingSnapshotsSuccess({
                    //     snapshotsByWindowId: response.snapshot_data_by_window_id,
                    // })
                }

                return metadata
            },
            addDiffToRecordingMetaPinnedCount: ({ diffCount }) => {
                return {
                    ...values.sessionPlayerMetaData,
                    pinnedCount: Math.max(values.sessionPlayerMetaData.pinnedCount + diffCount, 0),
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
                    const response = await api.get(apiUrl)
                    breakpoint()

                    // NOTE: This might seem backwards as we translate the snapshotsByWindowId to an array and then derive it again later but
                    // this is for future support of the API that will return them as a simple array

                    const incomingSnapshotByWindowId: {
                        [key: string]: eventWithTime[]
                    } = response.snapshot_data_by_window_id

                    const snapshots: RecordingSnapshot[] = Object.entries(incomingSnapshotByWindowId)
                        .flatMap(([windowId, snapshots]) => {
                            return snapshots.map((snapshot) => ({
                                ...snapshot,
                                windowId,
                            }))
                        })
                        .concat(nextUrl ? values.sessionPlayerSnapshotData?.snapshots ?? [] : [])
                        .sort((a, b) => a.timestamp - b.timestamp)

                    return {
                        snapshots,
                        next: response.next,
                    }
                },
            },
        ],
        sessionEventsData: [
            null as null | RecordingEventType[],
            {
                loadEvents: async () => {
                    if (!values.sessionPlayerData?.person) {
                        return null
                    }

                    const { start, end, person } = values.sessionPlayerData

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

                    // TODO: Somehow check whether or not we need to load more data.
                    try {
                        const res: any = await api.query({
                            kind: 'HogQLQuery',
                            query: `select properties from events where uuid = '${event.id}' and timestamp = toDateTime('${event.timestamp}') limit 1`,
                        })

                        if (res.results[0]) {
                            existingEvent.properties = JSON.parse(res.results[0])
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

                    if (!start || !values.hasAvailableFeature(AvailableFeature.RECORDINGS_PERFORMANCE)) {
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
            (s) => [s.sessionPlayerMetaData, s.snapshotsByWindowId, s.segments, s.bufferedTo],
            (meta, snapshotsByWindowId, segments, bufferedTo): SessionPlayerData => ({
                ...meta,
                snapshotsByWindowId,
                segments,
                bufferedTo,
            }),
        ],

        segments: [
            (s) => [s.sessionPlayerMetaData, s.sessionPlayerSnapshotData, s.snapshotsByWindowId],
            (sessionPlayerMetaData, sessionPlayerSnapshotData, snapshotsByWindowId): RecordingSegment[] => {
                return createSegments(sessionPlayerMetaData, sessionPlayerSnapshotData, snapshotsByWindowId)
            },
        ],

        snapshotsByWindowId: [
            (s) => [s.sessionPlayerSnapshotData],
            (sessionPlayerSnapshotData): Record<string, eventWithTime[]> => {
                const snapshots: Record<string, eventWithTime[]> = {}
                sessionPlayerSnapshotData?.snapshots.forEach((snapshot) => {
                    if (!snapshots[snapshot.windowId]) {
                        snapshots[snapshot.windowId] = []
                    }
                    snapshots[snapshot.windowId].push(snapshot)
                })
                return snapshots
            },
        ],

        bufferedTo: [
            (s) => [s.segments, s.snapshotsByWindowId],
            (segments, snapshotsByWindowId): (PlayerPosition & { timestamp: number }) | null => {
                // This is us building the snapshots live from the loaded snapshotData, instead of via the API

                let bufferedTo: (PlayerPosition & { timestamp: number }) | null = null
                // If we don't have metadata or snapshots yet, then we can't calculate the bufferedTo.
                if (!segments.length) {
                    return bufferedTo
                }

                // NOTE: Once we derive segments from the snapshot data this should be much easier to derive as we can simply say "what is the final timestamp that we have for all windows"
                for (const segment of segments) {
                    const windowSnapshots = snapshotsByWindowId?.[segment.windowId] ?? []
                    const lastEventForWindowId = windowSnapshots[windowSnapshots.length - 1]

                    if (lastEventForWindowId && lastEventForWindowId.timestamp >= segment.startTimeEpochMs) {
                        // If we've buffered past the start of the segment, see how far.
                        const windowStartTime = windowSnapshots[0].timestamp
                        const relativeTime = Math.min(
                            lastEventForWindowId.timestamp - windowStartTime,
                            segment.endPlayerPosition.time
                        )
                        bufferedTo = {
                            windowId: segment.windowId,
                            time: relativeTime,
                            timestamp: windowStartTime + relativeTime,
                        }
                    }
                }

                return bufferedTo
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

        if (props.sessionRecordingData) {
            // TODO: Fix this
            // actions.loadRecordingSnapshotsSuccess({
            //     snapshotsByWindowId: props.sessionRecordingData.snapshotsByWindowId,
            // })
            // NOTE: If we have to change this at all then likely old exported formats will need to be handled
            // TODO: Fix this to be backwards compatible with old format
            // We should be able to use the minimal info (end, start, duration etc.)
            // actions.loadRecordingMetaSuccess({
            //     person: props.sessionRecordingData.person,
            //     metadata: props.sessionRecordingData.metadata,
            // })
        }
    }),
])
