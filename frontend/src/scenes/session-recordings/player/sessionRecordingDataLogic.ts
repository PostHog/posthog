import { actions, afterMount, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { sum, toParams } from 'lib/utils'
import {
    AvailableFeature,
    PerformanceEvent,
    PlayerPosition,
    RecordingEventsFilters,
    RecordingEventType,
    RecordingReportLoadTimes,
    RecordingSegment,
    RecordingStartAndEndTime,
    SessionPlayerData,
    SessionPlayerMetaData,
    SessionPlayerSnapshotData,
    SessionRecordingId,
    SessionRecordingMeta,
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

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
const BUFFER_MS = 60000 // +- before and after start and end of a recording to query for.

export const parseMetadataResponse = (recording: SessionRecordingType): SessionRecordingMeta => {
    let startTimestamp: number = Infinity
    let endTimestamp: number = 0

    const segments: RecordingSegment[] =
        recording.segments?.map((segment): RecordingSegment => {
            const windowStartTime = +dayjs(recording.start_and_end_times_by_window_id?.[segment.window_id]?.start_time)
            const startTimeEpochMs = +dayjs(segment?.start_time)
            const endTimeEpochMs = +dayjs(segment?.end_time)
            const startPlayerPosition: PlayerPosition = {
                windowId: segment.window_id,
                time: startTimeEpochMs - windowStartTime,
            }
            const endPlayerPosition: PlayerPosition = {
                windowId: segment.window_id,
                time: endTimeEpochMs - windowStartTime,
            }
            const durationMs = endTimeEpochMs - startTimeEpochMs

            if (startTimeEpochMs < startTimestamp) {
                startTimestamp = startTimeEpochMs
            }
            if (endTimeEpochMs > endTimestamp) {
                endTimestamp = endTimeEpochMs
            }

            return {
                startPlayerPosition,
                endPlayerPosition,
                durationMs,
                startTimeEpochMs,
                endTimeEpochMs,
                windowId: segment.window_id,
                isActive: segment.is_active,
            }
        }) || []
    const startAndEndTimesByWindowId: Record<string, RecordingStartAndEndTime> = {}
    Object.entries(recording.start_and_end_times_by_window_id || {}).forEach(([windowId, startAndEndTimes]) => {
        startAndEndTimesByWindowId[windowId] = {
            startTimeEpochMs: +dayjs(startAndEndTimes.start_time),
            endTimeEpochMs: +dayjs(startAndEndTimes.end_time),
        }
    })
    return {
        pinnedCount: recording.pinned_count ?? 0,
        segments,
        startAndEndTimesByWindowId,
        recordingDurationMs: sum(segments.map((s) => s.durationMs)),
        startTimestamp,
        endTimestamp,
    }
}

const generateRecordingReportDurations = (
    cache: Record<string, any>,
    values: Record<string, any>
): RecordingReportLoadTimes => {
    return {
        metadata: {
            size: values.sessionPlayerMetaData.metadata.segments.length,
            duration: Math.round(performance.now() - cache.metaStartTime),
        },
        snapshots: {
            size: Object.keys(values.sessionPlayerSnapshotData?.snapshotsByWindowId ?? {}).length,
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

// Returns the maximum player position that the recording has been buffered to.
// Data can be received out of order (e.g. events from a later segment are received
// before events from an earlier segment). So this function iterates through the
// segments in their order and returns when it first detects data is not loaded.
const calculateBufferedTo = (
    segments: RecordingSegment[] = [],
    snapshotsByWindowId: Record<string, eventWithTime[]> | undefined,
    startAndEndTimesByWindowId: Record<string, RecordingStartAndEndTime> = {}
): PlayerPosition | null => {
    let bufferedTo: PlayerPosition | null = null
    // If we don't have metadata or snapshots yet, then we can't calculate the bufferedTo.
    if (!segments || !snapshotsByWindowId || !startAndEndTimesByWindowId) {
        return bufferedTo
    }

    for (const segment of segments) {
        const lastEventForWindowId = (snapshotsByWindowId[segment.windowId] ?? []).slice(-1).pop()

        if (lastEventForWindowId && lastEventForWindowId.timestamp >= segment.startTimeEpochMs) {
            // If we've buffered past the start of the segment, see how far.
            const windowStartTime = startAndEndTimesByWindowId[segment.windowId].startTimeEpochMs
            bufferedTo = {
                windowId: segment.windowId,
                time: Math.min(lastEventForWindowId.timestamp - windowStartTime, segment.endPlayerPosition.time),
            }
        }
    }

    return bufferedTo
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
            metadata: {
                pinnedCount: 0,
                segments: [],
                startAndEndTimesByWindowId: {},
                recordingDurationMs: 0,
                startTimestamp: 0,
                endTimestamp: 0,
            },
            bufferedTo: null,
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
            if (!values.sessionPlayerSnapshotData?.snapshotsByWindowId) {
                actions.loadRecordingSnapshots()
            }
            actions.loadEvents()
            actions.loadPerformanceEvents()
        },
        loadRecordingSnapshotsSuccess: () => {
            // If there is more data to poll for load the next batch.
            // This will keep calling loadRecording until `next` is empty.
            if (!!values.sessionPlayerData.next) {
                actions.loadRecordingSnapshots(values.sessionPlayerData.next)
            } else {
                actions.reportUsageIfFullyLoaded()
            }
            // Not always accurate that recording is playable after first chunk is loaded, but good guesstimate for now
            if (values.chunkPaginationIndex === 1) {
                cache.firstPaintDurationRow = {
                    size: Object.keys(values.sessionPlayerSnapshotData?.snapshotsByWindowId || {}).length,
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
    loaders(({ values, props, cache, actions }) => ({
        sessionPlayerMetaData: {
            loadRecordingMeta: async (_, breakpoint): Promise<SessionPlayerMetaData> => {
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
                    actions.loadRecordingSnapshotsSuccess({
                        snapshotsByWindowId: response.snapshot_data_by_window_id,
                    })
                }

                return {
                    ...values.sessionPlayerMetaData,
                    person: response.person || null,
                    metadata,
                }
            },
            addDiffToRecordingMetaPinnedCount: ({ diffCount }) => {
                return {
                    ...values.sessionPlayerMetaData,
                    metadata: {
                        ...values.sessionPlayerMetaData.metadata,
                        pinnedCount: Math.max(values.sessionPlayerMetaData.metadata.pinnedCount + diffCount, 0),
                    },
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
                    // If we have a next url, we need to append the new snapshots to the existing ones
                    const snapshotsByWindowId = {
                        ...(nextUrl ? values.sessionPlayerSnapshotData?.snapshotsByWindowId ?? {} : {}),
                    }
                    const incomingSnapshotByWindowId: {
                        [key: string]: eventWithTime[]
                    } = response.snapshot_data_by_window_id

                    // We merge the new snapshots with the existing ones and sort by timestamp to ensure they are in order
                    Object.entries(incomingSnapshotByWindowId).forEach(([windowId, snapshots]) => {
                        snapshotsByWindowId[windowId] = [...(snapshotsByWindowId[windowId] ?? []), ...snapshots].sort(
                            (a, b) => a.timestamp - b.timestamp
                        )
                    })
                    return {
                        ...values.sessionPlayerSnapshotData,
                        snapshotsByWindowId,
                        next: response.next,
                    }
                },
            },
        ],
        sessionEventsData: [
            null as null | RecordingEventType[],
            {
                loadEvents: async () => {
                    if (!values.sessionPlayerData?.person?.id || !values.recordingTimeWindow) {
                        return null
                    }

                    const res: any = await api.query({
                        kind: 'EventsQuery',
                        select: [
                            'uuid',
                            'event',
                            'timestamp',
                            'elements_chain',
                            'properties.$current_url',
                            'properties.$window_id',
                        ],
                        orderBy: ['timestamp ASC'],
                        limit: 1000000,
                        personId: values.sessionPlayerData.person.id,
                        properties: [
                            // TODO: Support loading events with no sessionId
                            {
                                key: '$session_id',
                                value: [props.sessionRecordingId],
                                operator: 'exact',
                                type: 'event',
                            },
                        ],
                    })

                    const { startTimestamp } = values.sessionPlayerData?.metadata || {}

                    const minimalEvents = res.results.map((event: any): RecordingEventType => {
                        return {
                            id: event[0],
                            event: event[1],
                            timestamp: event[2],
                            elements: chainToElements(event[3]),
                            properties: {
                                $current_url: event[4],
                                $window_id: event[5],
                            },
                            playerTime: +dayjs(event[2]) - startTimestamp,
                            fullyLoaded: false,
                        }
                    })
                    // We should add a buffer here as some events may fall slightly outside the range
                    // .filter(
                    //     (x: RecordingEventType) =>
                    //         x.playerTime !== null && x.playerTime > 0 && x.playerTime < recordingDurationMs
                    // )

                    return minimalEvents
                },

                loadFullEventData: async ({ event }) => {
                    const existingEvent = values.sessionEventsData?.find((x) => x.id === event.id)
                    if (!existingEvent || existingEvent.fullyLoaded) {
                        return values.sessionEventsData
                    }

                    // TODO: Somehow check whether or not we need to load more data.
                    const res: any = await api.query({
                        kind: 'HogQLQuery',
                        query: `select properties from events where uuid = '${event.id}' limit 1`,
                    })

                    if (res.results[0]) {
                        existingEvent.properties = JSON.parse(res.results[0])
                        existingEvent.fullyLoaded = true
                    }

                    return values.sessionEventsData
                },
            },
        ],

        performanceEvents: [
            null as null | PerformanceEvent[],
            {
                loadPerformanceEvents: async ({}, breakpoint) => {
                    cache.performanceEventsStartTime = performance.now()
                    if (
                        !values.recordingTimeWindow ||
                        !values.hasAvailableFeature(AvailableFeature.RECORDINGS_PERFORMANCE)
                    ) {
                        return []
                    }

                    await breakpoint(1)

                    // Use `nextUrl` if there is a `next` url to fetch
                    const response = await api.performanceEvents.list({
                        session_id: props.sessionRecordingId,
                        date_from: values.recordingTimeWindow.start.subtract(BUFFER_MS, 'ms').format(),
                        date_to: values.recordingTimeWindow.end.add(BUFFER_MS, 'ms').format(),
                    })

                    breakpoint()

                    return response.results
                },
            },
        ],
    })),
    selectors({
        sessionPlayerData: [
            (s) => [s.sessionPlayerMetaData, s.sessionPlayerSnapshotData],
            (meta, snapshots): SessionPlayerData => ({
                ...meta,
                ...(snapshots || {
                    snapshotsByWindowId: {},
                }),
                bufferedTo: calculateBufferedTo(
                    meta.metadata?.segments,
                    snapshots?.snapshotsByWindowId,
                    meta.metadata?.startAndEndTimesByWindowId
                ),
            }),
        ],

        recordingTimeWindow: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData): { start: Dayjs; end: Dayjs } | undefined => {
                const recordingStartTime = sessionPlayerData.metadata.segments.slice(0, 1).pop()?.startTimeEpochMs
                const recordingEndTime = sessionPlayerData.metadata.segments.slice(-1).pop()?.endTimeEpochMs

                if (!recordingStartTime || !recordingEndTime) {
                    return undefined
                }

                return {
                    start: dayjs.utc(recordingStartTime),
                    end: dayjs.utc(recordingEndTime),
                }
            },
        ],

        eventsApiParams: [
            (s) => [s.sessionPlayerData, s.recordingTimeWindow, (_, props) => props.sessionRecordingId],
            (sessionPlayerData, recordingTimeWindow, sessionRecordingId) => {
                if (!sessionPlayerData.person?.id || !recordingTimeWindow) {
                    return null
                }

                return {
                    person_id: sessionPlayerData.person.id,
                    after: recordingTimeWindow.start.subtract(BUFFER_MS, 'ms').format(),
                    before: recordingTimeWindow.end.add(BUFFER_MS, 'ms').format(),
                    orderBy: ['timestamp'],
                    properties: {
                        type: 'OR',
                        values: [
                            {
                                type: 'AND',
                                values: [
                                    { key: '$session_id', value: 'is_not_set', operator: 'is_not_set', type: 'event' },
                                ],
                            },
                            {
                                type: 'AND',
                                values: [
                                    {
                                        key: '$session_id',
                                        value: [sessionRecordingId],
                                        operator: 'exact',
                                        type: 'event',
                                    },
                                ],
                            },
                        ],
                    },
                }
            },
        ],
        windowIds: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData) => {
                return Object.keys(sessionPlayerData?.metadata?.startAndEndTimesByWindowId) ?? []
            },
        ],
    }),
    afterMount(({ props, actions }) => {
        if (props.sessionRecordingId) {
            actions.loadEntireRecording()
        }

        if (props.sessionRecordingData) {
            actions.loadRecordingSnapshotsSuccess({
                snapshotsByWindowId: props.sessionRecordingData.snapshotsByWindowId,
            })
            actions.loadRecordingMetaSuccess({
                person: props.sessionRecordingData.person,
                metadata: props.sessionRecordingData.metadata,
            })
        }
    }),
])
