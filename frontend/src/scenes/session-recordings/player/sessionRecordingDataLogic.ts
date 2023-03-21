import { actions, afterMount, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import {
    AvailableFeature,
    EventType,
    PerformanceEvent,
    PlayerPosition,
    RecordingEventsFilters,
    RecordingEventType,
    SessionPlayerData,
    SessionPlayerMetaData,
    SessionPlayerSnapshotData,
    SessionRecordingEvents,
    SessionRecordingId,
    SessionRecordingUsageType,
} from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Dayjs, dayjs } from 'lib/dayjs'
import {
    getPlayerPositionFromEpochTime,
    getPlayerTimeFromPlayerPosition,
    guessPlayerPositionFromEpochTimeWithoutWindowId,
} from './playerUtils'
import type { sessionRecordingDataLogicType } from './sessionRecordingDataLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import {
    BUFFER_MS,
    calculateBufferedTo,
    generateRecordingReportDurations,
    IS_TEST_MODE,
    parseMetadataResponse,
    parseSnapshotResponse,
} from './recordingDataUtils'

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
        loadEvents: (nextUrl?: string) => ({ nextUrl }),
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
            // Fetch next events
            if (!!values.sessionEventsData?.next) {
                actions.loadEvents(values.sessionEventsData.next)
            } else {
                actions.reportUsageIfFullyLoaded()
            }
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

                    const snapshotData = parseSnapshotResponse(
                        response,
                        values.sessionPlayerSnapshotData,
                        values.sessionPlayerMetaData.metadata.startAndEndTimesByWindowId
                    )

                    return {
                        ...snapshotData,
                        next: response.next,
                    }
                },
            },
        ],
        sessionEventsData: [
            null as null | SessionRecordingEvents,
            {
                loadEvents: async ({ nextUrl }, breakpoint) => {
                    cache.eventsStartTime = performance.now()
                    if (!values.eventsApiParams) {
                        return values.sessionEventsData
                    }
                    await breakpoint(1)
                    // Use `nextUrl` if there is a `next` url to fetch
                    const apiUrl =
                        nextUrl || `api/projects/${values.currentTeamId}/events?${toParams(values.eventsApiParams)}`
                    const response = await api.get(apiUrl)
                    breakpoint()

                    let allEvents = []
                    // If the recording uses window_ids, then we only show events that map to the segments
                    const eventsWithPlayerData: RecordingEventType[] = []
                    const events = response.results ?? []

                    events.forEach((event: EventType) => {
                        // Events from other $session_ids should already be filtered out here so we don't need to worry about that
                        const eventEpochTimeOfEvent = +dayjs(event.timestamp)
                        let eventPlayerPosition: PlayerPosition | null = null

                        // 1. If it doesn't have a $window_id, then it is likely server side - include it on any window where the time overlaps
                        if (!event.properties.$window_id) {
                            // Handle the case where the event is 'out of band' for the recording (it has no window_id).
                            // This is the case where the event came from outside the recording (e.g. a server side event)
                            // But it happens to overlap in time with the recording
                            eventPlayerPosition = guessPlayerPositionFromEpochTimeWithoutWindowId(
                                eventEpochTimeOfEvent,
                                values.sessionPlayerData?.metadata?.startAndEndTimesByWindowId,
                                values.sessionPlayerData?.metadata?.segments
                            )
                        } else {
                            // 2. If it does have a $window_id, then link it to the window in question
                            eventPlayerPosition = getPlayerPositionFromEpochTime(
                                eventEpochTimeOfEvent,
                                event.properties.$window_id, // If there is no window_id on the event to match the recording metadata
                                values.sessionPlayerData.metadata.startAndEndTimesByWindowId
                            )
                        }

                        if (eventPlayerPosition !== null) {
                            const eventPlayerTime = getPlayerTimeFromPlayerPosition(
                                eventPlayerPosition,
                                values.sessionPlayerData.segments
                            )
                            if (eventPlayerTime !== null) {
                                eventsWithPlayerData.push({
                                    ...event,
                                    playerTime: eventPlayerTime,
                                    playerPosition: eventPlayerPosition,
                                    capturedInWindow: !!event.properties.$window_id,
                                })
                            }
                        }
                    })
                    // If we have a next url, we need to append the new events to the existing ones
                    allEvents = [
                        ...(nextUrl ? values.sessionEventsData?.events ?? [] : []),
                        ...eventsWithPlayerData,
                    ].sort(function (a, b) {
                        return (a.playerTime ?? 0) - (b.playerTime ?? 0)
                    })

                    return {
                        ...values.sessionEventsData,
                        next: response?.next,
                        events: allEvents,
                    }
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
            (meta, snapshots): SessionPlayerData => {
                return {
                    ...meta,
                    ...(snapshots || {
                        snapshotsByWindowId: {},
                        segments: [],
                        startAndEndTimesByWindowId: meta.metadata.startAndEndTimesByWindowId,
                    }),
                    bufferedTo: snapshots ? calculateBufferedTo(snapshots) : null,
                }
            },
        ],

        recordingTimeWindow: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData): { start: Dayjs; end: Dayjs } | undefined => {
                const recordingStartTime = (sessionPlayerData.segments ?? []).slice(0, 1).pop()?.startTimeEpochMs
                const recordingEndTime = (sessionPlayerData.segments ?? []).slice(-1).pop()?.endTimeEpochMs

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
