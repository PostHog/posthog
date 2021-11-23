import { kea } from 'kea'
import Fuse from 'fuse.js'
import api from 'lib/api'
import { clamp, errorToast, eventToDescription, toParams } from 'lib/utils'
import { sessionRecordingLogicType } from './sessionRecordingLogicType'
import {
    EventType,
    RecordingEventsFilters,
    RecordingEventType,
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

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export const parseMetadataResponse = (metadata: Record<string, any>): Partial<SessionRecordingMeta> => {
    return {
        ...(metadata ?? {}),
        start_time: metadata?.start_time ? +dayjs(metadata?.start_time) : 0,
        end_time: metadata?.end_time ? +dayjs(metadata?.end_time) : 0,
        recording_duration: parseFloat(metadata?.recording_duration) * 1000 || 0,
    }
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
        sessionPlayerDataLoading: [
            false,
            {
                loadRecordingSnapshotsSuccess: (_, { sessionPlayerData }) => {
                    // If sessionPlayerData doesn't have a next url, it means the entire recording is still loading.
                    return !!sessionPlayerData?.next
                },
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
                const params = toParams({ save_view: true })
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/session_recordings/${sessionRecordingId}?${params}`
                )
                breakpoint()
                return {
                    ...response.result,
                    session_recording: parseMetadataResponse(response.result?.session_recording),
                    snapshots: values.sessionPlayerData?.snapshots ?? [],
                }
            },
            loadRecordingSnapshots: async ({ sessionRecordingId, url }, breakpoint): Promise<SessionPlayerData> => {
                const apiUrl =
                    url || `api/projects/${values.currentTeamId}/session_recordings/${sessionRecordingId}/snapshots`
                const response = await api.get(apiUrl)
                breakpoint()
                const currData = values.sessionPlayerData
                return {
                    ...currData,
                    next: response.result?.next,
                    snapshots: [...(currData?.snapshots ?? []), ...(response.result?.snapshots ?? [])],
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

                return {
                    ...values.sessionEventsData,
                    next: response?.next,
                    events: [...(values.sessionEventsData?.events ?? []), ...(response.results ?? [])],
                }
            },
        },
    }),
    selectors: {
        loading: [
            (selectors) => [selectors.sessionEventsDataLoading, selectors.sessionPlayerDataLoading],
            (eventsLoading, playerLoading) => eventsLoading || playerLoading,
        ],
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
        firstChunkLoaded: [
            (selectors) => [selectors.chunkPaginationIndex],
            (chunkPaginationIndex) => chunkPaginationIndex > 0,
        ],
        isPlayable: [
            (selectors) => [
                selectors.firstChunkLoaded,
                selectors.sessionPlayerDataLoading,
                selectors.sessionPlayerData,
            ],
            (firstChunkLoaded, sessionPlayerDataLoading, sessionPlayerData) =>
                (firstChunkLoaded || // If first chunk is ready
                    !sessionPlayerDataLoading) && // data isn't being fetched
                sessionPlayerData?.snapshots.length > 1 && // more than one snapshot needed to init rrweb Replayer
                !!sessionPlayerData?.snapshots?.find((s: eventWithTime) => s.type === 2), // there's a full snapshot in the data that was loaded
        ],
        eventsApiParams: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => {
                if (
                    !sessionPlayerData?.person?.id ||
                    !sessionPlayerData?.session_recording?.start_time ||
                    !sessionPlayerData?.session_recording?.recording_duration
                ) {
                    return null
                }

                const buffer_ms = 60000 // +- before and after start and end of a recording to query for.
                return {
                    person_id: sessionPlayerData.person.id,
                    after: dayjs.utc(sessionPlayerData.session_recording.start_time).subtract(buffer_ms, 'ms').format(),
                    before: dayjs.utc(sessionPlayerData.session_recording.end_time).add(buffer_ms, 'ms').format(),
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
