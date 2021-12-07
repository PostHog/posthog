import { kea } from 'kea'
import Fuse from 'fuse.js'
import api from 'lib/api'
import { clamp, errorToast, eventToDescription, toParams } from 'lib/utils'
import { sessionRecordingLogicType } from './sessionRecordingLogicType'
import {
    EventType,
    PlayerPosition,
    RecordingEventsFilters,
    RecordingEventType,
    RecordingSegment,
    SessionPlayerData,
    SessionRecordingId,
    SessionRecordingMeta,
    SessionRecordingUsageType,
} from '~/types'
import { eventUsageLogic, RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { teamLogic } from '../teamLogic'
import { eventWithTime } from 'rrweb/typings/types'
import { getKeyMapping } from 'lib/components/PropertyKeyInfo'
import { dayjs } from 'lib/dayjs'
import { getPlayerPositionFromEpochTime, getPlayerTimeFromPlayerPosition } from './player/sessionRecordingPlayerLogic'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export interface UnparsedRecordingSegment {
    start_time: string
    end_time: string
    window_id: string
    is_active: boolean
    distinct_id: string
}

export const parseMetadataResponse = (metadata: Record<string, any>): Partial<SessionRecordingMeta> => {
    const segments: RecordingSegment[] = metadata.segment_playlist.map(
        (segment: UnparsedRecordingSegment): RecordingSegment => {
            const windowStartTime = +dayjs(metadata.start_and_end_times_by_window_id[segment.window_id].start_time)
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
                windowId: segment?.window_id,
                isActive: segment?.is_active,
            }
        }
    )
    return {
        segments,
        startAndEndTimesByWindowId: metadata.start_and_end_times_by_window_id,
        recordingDurationMs: segments.map((s) => s.durationMs).reduce((a, b) => a + b),
        distinctId: metadata.distinct_id,
    }
}

const calculateBufferedTo = (
    segments: RecordingSegment[] = [],
    snapshotsByWindowId: Record<string, eventWithTime[]>,
    startAndEndTimesByWindowId: Record<string, Record<string, number>> = {}
): PlayerPosition | null => {
    let bufferedTo: PlayerPosition | null = null
    if (segments && snapshotsByWindowId && startAndEndTimesByWindowId) {
        for (const segment of segments) {
            const lastEventForWindowId = (snapshotsByWindowId[segment.windowId] ?? []).slice(-1).pop()

            if (lastEventForWindowId && lastEventForWindowId.timestamp >= segment.startTimeEpochMs) {
                bufferedTo = {
                    windowId: segment.windowId,
                    time:
                        lastEventForWindowId.timestamp -
                        +dayjs(startAndEndTimesByWindowId[segment.windowId]['start_time']),
                }
            } else {
                return bufferedTo
            }
        }
    }
    return bufferedTo
}

// TODO: Replace this with permanent querying alternative in backend. Filtering on frontend should do for now.
const makeEventsQueryable = (events: RecordingEventType[]): RecordingEventType[] => {
    return events.map((e) => ({
        ...e,
        queryValue: `${getKeyMapping(e.event, 'event')?.label ?? e.event ?? ''} ${eventToDescription(e)}`.replace(
            /['"]+/g,
            ''
        ),
    }))
}

export const sessionRecordingLogic = kea<sessionRecordingLogicType>({
    path: ['scenes', 'session-recordings', 'sessionRecordingLogic'],
    connect: {
        logic: [eventUsageLogic],
        values: [teamLogic, ['currentTeamId']],
    },
    actions: {
        setFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
        setSource: (source: RecordingWatchedSource) => ({ source }),
        reportUsage: (recordingData: SessionPlayerData, loadTime: number) => ({
            recordingData,
            loadTime,
        }),
        loadRecordingMeta: (sessionRecordingId?: string) => ({ sessionRecordingId }),
        loadRecordingSnapshots: (sessionRecordingId?: string, url?: string) => ({ sessionRecordingId, url }),
        loadEvents: (url?: string) => ({ url }),
    },
    reducers: {
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
        sessionEventsDataLoading: [
            false,
            {
                loadEventsSuccess: (_, { sessionEventsData }) => {
                    return !!sessionEventsData?.next
                },
            },
        ],
        source: [
            RecordingWatchedSource.Unknown as RecordingWatchedSource,
            {
                setSource: (_, { source }) => source,
            },
        ],
    },
    listeners: ({ values, actions, sharedListeners, cache }) => ({
        loadRecordingMetaSuccess: () => {
            cache.eventsStartTime = performance.now()
            actions.loadEvents()
        },
        loadRecordingSnapshotsSuccess: () => {
            // If there is more data to poll for load the next batch.
            // This will keep calling loadRecording until `next` is empty.
            if (!!values.sessionPlayerData?.next) {
                actions.loadRecordingSnapshots(undefined, values.sessionPlayerData.next)
            }
            // Finished loading entire recording. Now make it known!
            else {
                eventUsageLogic.actions.reportRecording(
                    values.sessionPlayerData,
                    values.source,
                    performance.now() - cache.startTime,
                    SessionRecordingUsageType.LOADED,
                    0
                )
            }
            // Not always accurate that recording is playable after first chunk is loaded, but good guesstimate for now
            if (values.chunkPaginationIndex === 1) {
                actions.reportUsage(values.sessionPlayerData, performance.now() - cache.startTime)
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
                    values.sessionEvents.length ?? 0,
                    performance.now() - cache.eventsStartTime
                )
                cache.eventsStartTime = null
            }
        },
        loadRecordingMetaFailure: sharedListeners.showErrorToast,
        loadRecordingSnapshotsFailure: sharedListeners.showErrorToast,
        loadEventsFailure: sharedListeners.showErrorToast,
        reportUsage: async ({ recordingData, loadTime }, breakpoint) => {
            await breakpoint()
            eventUsageLogic.actions.reportRecording(
                recordingData,
                values.source,
                loadTime,
                SessionRecordingUsageType.VIEWED,
                0
            )
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportRecording(
                recordingData,
                values.source,
                loadTime,
                SessionRecordingUsageType.ANALYZED,
                10
            )
        },
    }),
    sharedListeners: () => ({
        showErrorToast: ({ error }) => {
            errorToast(
                'Error fetching information for your session recording',
                'The following error response was returned:',
                error
            )
        },
    }),
    loaders: ({ values }) => ({
        sessionPlayerData: {
            loadRecordingMeta: async ({ sessionRecordingId }, breakpoint): Promise<SessionPlayerData> => {
                const params = toParams({
                    save_view: true,
                    include_active_segments: true,
                })
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/session_recordings/${sessionRecordingId}?${params}`
                )
                const metadata = parseMetadataResponse(response.result?.session_recording)
                const bufferedTo = calculateBufferedTo(
                    metadata.segments,
                    values.sessionPlayerData?.snapshotsByWindowId,
                    metadata.startAndEndTimesByWindowId
                )
                breakpoint()
                return {
                    ...response.result,
                    metadata,
                    bufferedTo,
                    snapshotsByWindowId: { ...values.sessionPlayerData?.snapshotsByWindowId } ?? {},
                }
            },
            loadRecordingSnapshots: async ({ sessionRecordingId, url }, breakpoint): Promise<SessionPlayerData> => {
                const apiUrl =
                    url || `api/projects/${values.currentTeamId}/session_recordings/${sessionRecordingId}/snapshots`
                const response = await api.get(apiUrl)
                breakpoint()
                const snapshotsByWindowId = { ...(values.sessionPlayerData?.snapshotsByWindowId ?? {}) }
                const incomingSnapshotByWindowId: {
                    [key: string]: eventWithTime[]
                } = response.result?.snapshot_data_by_window_id
                Object.entries(incomingSnapshotByWindowId).forEach(([windowId, snapshots]) => {
                    snapshotsByWindowId[windowId] = [...(snapshotsByWindowId[windowId] ?? []), ...snapshots]
                })
                const bufferedTo = calculateBufferedTo(
                    values.sessionPlayerData?.metadata?.segments,
                    snapshotsByWindowId,
                    values.sessionPlayerData?.metadata?.startAndEndTimesByWindowId
                )
                return {
                    ...values.sessionPlayerData,
                    bufferedTo,
                    snapshotsByWindowId,
                    next: response.result?.next,
                }
            },
        },
        sessionEventsData: {
            loadEvents: async ({ url }, breakpoint) => {
                if (!values.eventsApiParams) {
                    return values.sessionEventsData
                }
                // Use `url` if there is a `next` url to fetch
                const apiUrl = url || `api/projects/${values.currentTeamId}/events?${toParams(values.eventsApiParams)}`
                const response = await api.get(apiUrl)
                breakpoint()

                let allEvents = []
                // If the recording uses window_ids, then we only show events that map to the segments
                const usesWindowId = !!values.sessionPlayerData?.metadata?.segments[0]?.windowId
                if (usesWindowId) {
                    const eventsWithPlayerData: RecordingEventType[] = []
                    const events = response.results ?? []
                    events.forEach((event: EventType) => {
                        const eventPlayerPosition = getPlayerPositionFromEpochTime(
                            +dayjs(event.timestamp),
                            event.properties.$window_id,
                            values.sessionPlayerData?.metadata?.startAndEndTimesByWindowId
                        )
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
                                })
                            }
                        }
                    })
                    allEvents = [...(values.sessionEventsData?.events ?? []), ...eventsWithPlayerData].sort(function (
                        a,
                        b
                    ) {
                        return a.playerTime - b.playerTime
                    })
                } else {
                    allEvents = [...(values.sessionEventsData?.events ?? []), ...(response.results ?? [])]
                }

                return {
                    ...values.sessionEventsData,
                    next: response?.next,
                    events: allEvents,
                }
            },
        },
    }),
    selectors: {
        sessionEvents: [
            (selectors) => [selectors.sessionEventsData, selectors.sessionPlayerData],
            (eventsData, playerData) => {
                return (eventsData?.events ?? []).map((e: EventType) => ({
                    ...e,
                    timestamp: +dayjs(e.timestamp),
                    zeroOffsetTime:
                        clamp(
                            +dayjs(e.timestamp),
                            playerData.session_recording.start_time,
                            playerData.session_recording.end_time
                        ) - playerData.session_recording.start_time,
                }))
            },
        ],
        eventsToShow: [
            (selectors) => [selectors.filters, selectors.sessionEvents],
            (filters, events) => {
                return filters?.query
                    ? new Fuse<RecordingEventType>(makeEventsQueryable(events), {
                          threshold: 0.3,
                          keys: ['queryValue'],
                          findAllMatches: true,
                          ignoreLocation: true,
                          sortFn: (a, b) => events[a.idx].timestamp - events[b.idx].timestamp || a.score - b.score,
                      })
                          .search(filters.query)
                          .map((result) => result.item)
                    : events
            },
        ],
        eventsApiParams: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => {
                console.log('aaaaaaa', sessionPlayerData.metadata.segments.slice(0, 1).pop())
                const recordingStartTime = sessionPlayerData.metadata.segments.slice(0, 1).pop()?.startTimeEpochMs
                const recordingEndTime = sessionPlayerData.metadata.segments.slice(-1).pop()?.endTimeEpochMs
                if (!sessionPlayerData?.person?.id || !recordingStartTime || !recordingEndTime) {
                    return null
                }

                const buffer_ms = 60000 // +- before and after start and end of a recording to query for.
                return {
                    person_id: sessionPlayerData.person.id,
                    after: dayjs.utc(recordingStartTime).subtract(buffer_ms, 'ms').format(),
                    before: dayjs.utc(recordingEndTime).add(buffer_ms, 'ms').format(),
                    limit: 1000,
                    orderBy: ['timestamp'],
                }
            },
        ],
    },
    urlToAction: ({ actions, values, cache }) => {
        const urlToAction = (
            _: any,
            params: {
                sessionRecordingId?: SessionRecordingId
                source?: string
            }
        ): void => {
            const { sessionRecordingId, source } = params
            if (source && (Object.values(RecordingWatchedSource) as string[]).includes(source)) {
                actions.setSource(source as RecordingWatchedSource)
            }
            if (values && sessionRecordingId !== values.sessionRecordingId && sessionRecordingId) {
                // Load meta first. Snapshots are loaded once Replayer ref is mounted in sessionRecordingPlayerLogic
                cache.startTime = performance.now()
                actions.loadRecordingMeta(sessionRecordingId)
                actions.loadRecordingSnapshots(sessionRecordingId)
            }
        }

        return {
            '/sessions': urlToAction,
            '/recordings': urlToAction,
            '/person/*': urlToAction,
        }
    },
})
