import { actions, afterMount, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { sum, toParams } from 'lib/utils'
import {
    AvailableFeature,
    EventType,
    PerformanceEvent,
    PlayerPosition,
    RecordingEventsFilters,
    RecordingEventType,
    RecordingSegment,
    RecordingStartAndEndTime,
    SessionPlayerData,
    SessionPlayerMetaData,
    SessionPlayerSnapshotData,
    SessionRecordingEvents,
    SessionRecordingId,
    SessionRecordingMeta,
    SessionRecordingPlaylistType,
    SessionRecordingUsageType,
} from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { eventWithTime } from 'rrweb/typings/types'
import { dayjs } from 'lib/dayjs'
import {
    getPlayerPositionFromEpochTime,
    getPlayerTimeFromPlayerPosition,
    guessPlayerPositionFromEpochTimeWithoutWindowId,
} from './playerUtils'
import type { sessionRecordingDataLogicType } from './sessionRecordingDataLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'
import { createPerformanceSummaryEvents } from './inspector/v2/utils'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export interface UnparsedRecordingSegment {
    start_time: string
    end_time: string
    window_id: string
    is_active: boolean
}

export interface UnparsedMetadata {
    session_id: string
    viewed: boolean
    segments: UnparsedRecordingSegment[]
    start_and_end_times_by_window_id: Record<string, Record<string, string>>
    playlists: SessionRecordingPlaylistType['id'][]
}

export const parseMetadataResponse = (metadata?: UnparsedMetadata): SessionRecordingMeta => {
    const segments: RecordingSegment[] =
        metadata?.segments.map((segment: UnparsedRecordingSegment): RecordingSegment => {
            const windowStartTime = +dayjs(metadata?.start_and_end_times_by_window_id[segment.window_id].start_time)
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
    Object.entries(metadata?.start_and_end_times_by_window_id || {}).forEach(([windowId, startAndEndTimes]) => {
        startAndEndTimesByWindowId[windowId] = {
            startTimeEpochMs: +dayjs(startAndEndTimes.start_time),
            endTimeEpochMs: +dayjs(startAndEndTimes.end_time),
        }
    })
    return {
        segments,
        startAndEndTimesByWindowId,
        recordingDurationMs: sum(segments.map((s) => s.durationMs)),
        playlists: metadata?.playlists ?? [],
    }
}

// Returns the maximum player position that the recording has been buffered to.
// Data can be received out of order (e.g. events from a later segment are received
// before events from an earlier segment). So this function iterates through the
// segments in their order and returns when it first detects data is not loaded.
const calculateBufferedTo = (
    segments: RecordingSegment[] = [],
    snapshotsByWindowId: Record<string, eventWithTime[]>,
    startAndEndTimesByWindowId: Record<string, RecordingStartAndEndTime> = {}
): PlayerPosition | null => {
    let bufferedTo: PlayerPosition | null = null
    // If we don't have metadata or snapshots yet, then we can't calculate the bufferedTo.
    if (segments && snapshotsByWindowId && startAndEndTimesByWindowId) {
        for (const segment of segments) {
            const lastEventForWindowId = (snapshotsByWindowId[segment.windowId] ?? []).slice(-1).pop()

            if (lastEventForWindowId && lastEventForWindowId.timestamp >= segment.startTimeEpochMs) {
                // If we've buffered past the start of the segment, see how far.
                const windowStartTime = startAndEndTimesByWindowId[segment.windowId].startTimeEpochMs
                bufferedTo = {
                    windowId: segment.windowId,
                    time: Math.min(lastEventForWindowId.timestamp - windowStartTime, segment.endPlayerPosition.time),
                }
            } else {
                // If we haven't buffered past the start of the segment, then return our current bufferedTo.
                return bufferedTo
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
        values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags'], userLogic, ['hasAvailableFeature']],
    }),
    defaults({
        sessionPlayerMetaData: {
            person: null,
            metadata: {
                segments: [],
                startAndEndTimesByWindowId: {},
                recordingDurationMs: 0,
                playlists: [],
            },
            bufferedTo: null,
        } as SessionPlayerMetaData,
        sessionPlayerSnapshotData: {
            snapshotsByWindowId: {},
            next: undefined,
        } as SessionPlayerSnapshotData,
    }),
    actions({
        setFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
        loadEntireRecording: true,
        loadRecordingMeta: true,
        setRecordingMeta: (metadata: Partial<SessionPlayerMetaData>) => ({ metadata }),
        loadRecordingSnapshots: (nextUrl?: string) => ({ nextUrl }),
        loadEvents: (nextUrl?: string) => ({ nextUrl }),
        loadPerformanceEvents: (nextUrl?: string) => ({ nextUrl }),
        reportUsage: (type: SessionRecordingUsageType) => ({ type }),
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
            actions.loadRecordingSnapshots()
        },
        loadRecordingMetaSuccess: () => {
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
                    size: Object.keys(values.sessionPlayerSnapshotData.snapshotsByWindowId).length,
                    duration: Math.round(performance.now() - cache.snapshotsStartTime),
                }

                actions.reportUsage(SessionRecordingUsageType.VIEWED)
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
                actions.reportUsage(SessionRecordingUsageType.LOADED)
            }
        },
        reportUsage: async ({ type }, breakpoint) => {
            const durations = {
                metadata: {
                    size: values.sessionPlayerMetaData.metadata.segments.length,
                    duration: Math.round(performance.now() - cache.metaStartTime),
                },
                snapshots: {
                    size: Object.keys(values.sessionPlayerSnapshotData.snapshotsByWindowId).length,
                    duration: Math.round(performance.now() - cache.snapshotsStartTime),
                },
                events: {
                    size: values.sessionEventsData?.events?.length ?? 0,
                    duration: Math.round(performance.now() - cache.eventsStartTime),
                },
                performanceEvents: {
                    size: values.performanceEvents?.length ?? 0,
                    duration: Math.round(performance.now() - cache.performanceEventsStartTime),
                },
                firstPaint: cache.firstPaintDurationRow,
            }
            await breakpoint()

            if (type === SessionRecordingUsageType.LOADED) {
                eventUsageLogic.actions.reportRecording(
                    values.sessionPlayerData,
                    durations,
                    SessionRecordingUsageType.LOADED,
                    0
                )
                // Reset cache now that final usage report has been sent
                cache.metaStartTime = null
                cache.snapshotsStartTime = null
                cache.eventsStartTime = null
                cache.performanceEventsStartTime = null
                cache.firstPaintDurationRow = null
            } else {
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
            }
        },
    })),
    loaders(({ values, props, cache }) => ({
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
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/session_recordings/${props.sessionRecordingId}?${params}`
                )

                const unparsedMetadata: UnparsedMetadata | undefined = response.result?.session_recording
                const metadata = parseMetadataResponse(unparsedMetadata)
                breakpoint()
                return {
                    ...values.sessionPlayerMetaData,
                    person: response.result?.person,
                    metadata,
                }
            },
            setRecordingMeta: ({ metadata }) => ({
                ...values.sessionPlayerMetaData,
                ...metadata,
            }),
        },
        sessionPlayerSnapshotData: {
            loadRecordingSnapshots: async ({ nextUrl }, breakpoint): Promise<SessionPlayerSnapshotData> => {
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
                    ...(nextUrl ? values.sessionPlayerSnapshotData.snapshotsByWindowId ?? {} : {}),
                }
                const incomingSnapshotByWindowId: {
                    [key: string]: eventWithTime[]
                } = response.result?.snapshot_data_by_window_id
                Object.entries(incomingSnapshotByWindowId).forEach(([windowId, snapshots]) => {
                    snapshotsByWindowId[windowId] = [...(snapshotsByWindowId[windowId] ?? []), ...snapshots]
                })
                return {
                    ...values.sessionPlayerSnapshotData,
                    snapshotsByWindowId,
                    next: response.result?.next,
                }
            },
        },
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
                                values.sessionPlayerData.metadata.segments
                            )
                            if (eventPlayerTime !== null) {
                                eventsWithPlayerData.push({
                                    ...event,
                                    playerTime: eventPlayerTime,
                                    playerPosition: eventPlayerPosition,
                                    capturedInWindow: !!event.properties.$window_id,
                                    percentageOfRecordingDuration: values.sessionPlayerData.metadata.recordingDurationMs
                                        ? (100 * eventPlayerTime) /
                                          values.sessionPlayerData.metadata.recordingDurationMs
                                        : 0,
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
                        !values.featureFlags[FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE] ||
                        !values.hasAvailableFeature(AvailableFeature.RECORDINGS_PERFORMANCE)
                    ) {
                        return null
                    }

                    await breakpoint(1)
                    // Use `nextUrl` if there is a `next` url to fetch
                    const response = await api.performanceEvents.list({
                        session_id: props.sessionRecordingId,
                        date_from: values.eventsApiParams?.after,
                        date_to: values.eventsApiParams?.before,
                    })

                    breakpoint()

                    return createPerformanceSummaryEvents(response.results ?? [])
                },
            },
        ],
    })),
    selectors({
        sessionPlayerData: [
            (s) => [s.sessionPlayerMetaData, s.sessionPlayerSnapshotData],
            (meta, snapshots): SessionPlayerData => ({
                ...meta,
                ...snapshots,
                bufferedTo: calculateBufferedTo(
                    meta.metadata?.segments,
                    snapshots.snapshotsByWindowId,
                    meta.metadata?.startAndEndTimesByWindowId
                ),
            }),
        ],

        eventsApiParams: [
            (selectors) => [selectors.sessionPlayerData, (_, props) => props.sessionRecordingId],
            (sessionPlayerData, sessionRecordingId) => {
                const recordingStartTime = sessionPlayerData.metadata.segments.slice(0, 1).pop()?.startTimeEpochMs
                const recordingEndTime = sessionPlayerData.metadata.segments.slice(-1).pop()?.endTimeEpochMs
                if (!sessionPlayerData.person?.id || !recordingStartTime || !recordingEndTime) {
                    return null
                }

                const buffer_ms = 60000 // +- before and after start and end of a recording to query for.

                return {
                    person_id: sessionPlayerData.person.id,
                    after: dayjs.utc(recordingStartTime).subtract(buffer_ms, 'ms').format(),
                    before: dayjs.utc(recordingEndTime).add(buffer_ms, 'ms').format(),
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
            actions.loadRecordingMetaSuccess({
                person: props.sessionRecordingData.person,
                metadata: props.sessionRecordingData.metadata,
            })
            actions.loadRecordingSnapshotsSuccess({
                snapshotsByWindowId: props.sessionRecordingData.snapshotsByWindowId,
            })
        }
    }),
])
