import { kea } from 'kea'
import Fuse from 'fuse.js'
import api from 'lib/api'
import { errorToast, eventToDescription, sum, toParams } from 'lib/utils'
import { sessionRecordingLogicType } from './sessionRecordingLogicType'
import {
    EventType,
    PlayerPosition,
    RecordingEventsFilters,
    RecordingEventType,
    RecordingSegment,
    RecordingStartAndEndTime,
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
import { getPlayerPositionFromEpochTime, getPlayerTimeFromPlayerPosition } from './player/playerUtils'

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

export const parseMetadataResponse = (metadata: UnparsedMetadata): Partial<SessionRecordingMeta> => {
    const segments: RecordingSegment[] = metadata.segments.map(
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
                windowId: segment.window_id,
                isActive: segment.is_active,
            }
        }
    )
    const startAndEndTimesByWindowId: Record<string, RecordingStartAndEndTime> = {}
    Object.entries(metadata.start_and_end_times_by_window_id).forEach(([windowId, startAndEndTimes]) => {
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
                    values.sessionEventsData?.events?.length ?? 0,
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
                })
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/session_recordings/${sessionRecordingId}?${params}`
                )
                const unparsedMetadata: UnparsedMetadata = response.result?.session_recording
                const metadata = parseMetadataResponse(unparsedMetadata)
                const bufferedTo = calculateBufferedTo(
                    metadata.segments,
                    values.sessionPlayerData?.snapshotsByWindowId,
                    metadata.startAndEndTimesByWindowId
                )
                breakpoint()
                return {
                    ...values.sessionPlayerData,
                    person: response.result?.person,
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
                const eventsWithPlayerData: RecordingEventType[] = []
                const events = response.results ?? []
                events.forEach((event: EventType) => {
                    // Try to place the event 1 second before it happens, so the user actually sees it happen after clicking on it
                    let eventPlayerPosition = getPlayerPositionFromEpochTime(
                        +dayjs(event.timestamp) - 1000,
                        event.properties?.$window_id ?? '', // If there is no window_id on the event to match the recording metadata
                        values.sessionPlayerData?.metadata?.startAndEndTimesByWindowId
                    )
                    // If 1 seconds before the event is before the start of the recording, then use the actual timestamp
                    if (eventPlayerPosition === null) {
                        eventPlayerPosition = getPlayerPositionFromEpochTime(
                            +dayjs(event.timestamp),
                            event.properties?.$window_id ?? '', // If there is no window_id on the event to match the recording metadata
                            values.sessionPlayerData?.metadata?.startAndEndTimesByWindowId
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
                                percentageOfRecordingDuration:
                                    (100 * eventPlayerTime) / values.sessionPlayerData.metadata.recordingDurationMs,
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

                return {
                    ...values.sessionEventsData,
                    next: response?.next,
                    events: allEvents,
                }
            },
        },
    }),
    selectors: {
        eventsToShow: [
            (selectors) => [selectors.filters, selectors.sessionEventsData],
            (filters, sessionEventsData) => {
                const events = sessionEventsData?.events ?? []
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
                    orderBy: ['timestamp'],
                }
            },
        ],
    },
    urlToAction: ({ actions, values, cache }) => {
        const urlToAction = (
            _: any,
            params: {
                source?: string
            },
            hashParams: {
                sessionRecordingId?: SessionRecordingId
            }
        ): void => {
            const { source } = params
            const { sessionRecordingId } = hashParams
            if (source && (Object.values(RecordingWatchedSource) as string[]).includes(source)) {
                actions.setSource(source as RecordingWatchedSource)
            }
            if (values && sessionRecordingId && sessionRecordingId !== values.sessionRecordingId) {
                cache.startTime = performance.now()
                actions.loadRecordingMeta(sessionRecordingId)
                actions.loadRecordingSnapshots(sessionRecordingId)
            }
        }

        return {
            '/recordings': urlToAction,
            '/person/*': urlToAction,
            '/insights/*': urlToAction,
        }
    },
})
