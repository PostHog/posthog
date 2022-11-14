import { actions, afterMount, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { sum, toParams } from 'lib/utils'
import {
    EventType,
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
    recordingStartTime?: string
}

export const sessionRecordingDataLogic = kea<sessionRecordingDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionRecordingDataLogic', key]),
    props({} as SessionRecordingDataLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect({
        logic: [eventUsageLogic],
        values: [teamLogic, ['currentTeamId']],
    }),
    defaults({
        sessionPlayerMetaData: {
            person: null,
            metadata: {
                segments: [],
                startAndEndTimesByWindowId: {},
                recordingDurationMs: 0,
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
        reportUsage: (playerData: SessionPlayerData, loadTime: number) => ({
            playerData,
            loadTime,
        }),
        loadEntireRecording: true,
        loadRecordingMeta: true,
        loadRecordingSnapshots: (nextUrl?: string) => ({ nextUrl }),
        loadEvents: (nextUrl?: string) => ({ nextUrl }),
    }),
    reducers(({ cache }) => ({
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
        loadMetaTimeMs: [
            null as number | null,
            {
                loadRecordingMetaSuccess: () => (cache.loadStartTime ? performance.now() - cache.loadStartTime : null),
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
        loadFirstSnapshotTimeMs: [
            null as number | null,
            {
                loadRecordingSnapshotsSuccess: (prevLoadFirstSnapshotTimeMs) => {
                    return cache.loadStartTime && prevLoadFirstSnapshotTimeMs === null
                        ? performance.now() - cache.loadStartTime
                        : null
                },
            },
        ],
        loadAllSnapshotsTimeMs: [
            null as number | null,
            {
                loadRecordingSnapshotsSuccess: (_, actionData) => {
                    return cache.loadStartTime && actionData?.payload && !actionData.payload.nextUrl
                        ? performance.now() - cache.loadStartTime
                        : null
                },
            },
        ],
    })),
    listeners(({ values, actions, cache }) => ({
        loadEntireRecording: () => {
            cache.loadStartTime = performance.now()
            actions.loadRecordingMeta()
            actions.loadRecordingSnapshots()
        },
        loadRecordingMetaSuccess: () => {
            cache.eventsStartTime = performance.now()
            actions.loadEvents()
        },
        loadRecordingSnapshotsSuccess: () => {
            // If there is more data to poll for load the next batch.
            // This will keep calling loadRecording until `next` is empty.
            if (!!values.sessionPlayerData.next) {
                actions.loadRecordingSnapshots(values.sessionPlayerData.next)
            }
            // Finished loading entire recording. Now make it known!
            else {
                eventUsageLogic.actions.reportRecording(
                    values.sessionPlayerData,
                    performance.now() - cache.loadStartTime,
                    SessionRecordingUsageType.LOADED,
                    0
                )
            }
            // Not always accurate that recording is playable after first chunk is loaded, but good guesstimate for now
            if (values.chunkPaginationIndex === 1) {
                actions.reportUsage(values.sessionPlayerData, performance.now() - cache.loadStartTime)
            }
        },
        loadEventsSuccess: () => {
            // Fetch next events
            if (!!values.sessionEventsData?.next) {
                actions.loadEvents(values.sessionEventsData.next)
            }
            // Finished loading all events.
            else {
                eventUsageLogic.actions.reportRecordingEventsFetched(
                    values.sessionEventsData?.events?.length ?? 0,
                    performance.now() - cache.eventsStartTime
                )
                cache.eventsStartTime = null
            }
        },
        reportUsage: async ({ playerData, loadTime }, breakpoint) => {
            await breakpoint()
            eventUsageLogic.actions.reportRecording(playerData, loadTime, SessionRecordingUsageType.VIEWED, 0)
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportRecording(playerData, loadTime, SessionRecordingUsageType.ANALYZED, 10)
        },
    })),
    loaders(({ values, props }) => ({
        sessionPlayerMetaData: {
            loadRecordingMeta: async (_, breakpoint): Promise<SessionPlayerMetaData> => {
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
        },
        sessionPlayerSnapshotData: {
            loadRecordingSnapshots: async ({ nextUrl }, breakpoint): Promise<SessionPlayerSnapshotData> => {
                if (!props.sessionRecordingId) {
                    return values.sessionPlayerSnapshotData
                }
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
                    if (!values.eventsApiParams) {
                        return values.sessionEventsData
                    }
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
                        // If possible, place the event 1s before the actual event
                        const timesToAttemptToPlaceEvent = [+dayjs(event.timestamp) - 1000, +dayjs(event.timestamp)]
                        let eventPlayerPosition = null
                        let isOutOfBand = false
                        for (const eventEpochTimeToAttempt of timesToAttemptToPlaceEvent) {
                            if (
                                !event.properties.$window_id &&
                                !values.sessionPlayerData?.metadata?.startAndEndTimesByWindowId['']
                            ) {
                                // Handle the case where the event is 'out of band' for the recording (it has no window_id and
                                // the recording has window_ids). This is the case where the event came from
                                // outside the recording (e.g. a server side event) But it happens to overlap in time with the recording
                                eventPlayerPosition = guessPlayerPositionFromEpochTimeWithoutWindowId(
                                    eventEpochTimeToAttempt,
                                    values.sessionPlayerData?.metadata?.startAndEndTimesByWindowId,
                                    values.sessionPlayerData?.metadata?.segments
                                )
                                if (eventPlayerPosition) {
                                    isOutOfBand = true
                                    break
                                }
                            } else {
                                // Handle the normal events that fit within the recording
                                eventPlayerPosition = getPlayerPositionFromEpochTime(
                                    eventEpochTimeToAttempt,
                                    event.properties?.$window_id ?? '', // If there is no window_id on the event to match the recording metadata
                                    values.sessionPlayerData.metadata.startAndEndTimesByWindowId
                                )
                            }
                            if (eventPlayerPosition !== null) {
                                break
                            }
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
                                    isOutOfBand,
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
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => {
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
                }
            },
        ],
    }),
    afterMount(({ props, actions }) => {
        if (props.sessionRecordingId) {
            actions.loadEntireRecording()
        }
    }),
])
