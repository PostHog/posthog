import { kea } from 'kea'
import api from 'lib/api'
import { errorToast, eventToName, toParams } from 'lib/utils'
import { sessionsPlayLogicType } from './sessionsPlayLogicType'
import { SessionPlayerData, SessionRecordingEvents, SessionRecordingId, SessionType } from '~/types'
import { EventIndex } from '@posthog/react-rrweb-player'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { toast } from 'react-toastify'
import { eventUsageLogic, RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { eventWithTime } from 'rrweb/typings/types'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
dayjs.extend(utc)

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export const sessionsPlayLogic = kea<sessionsPlayLogicType>({
    connect: {
        logic: [eventUsageLogic],
        values: [sessionsTableLogic, ['sessions', 'pagination', 'orderedSessionRecordingIds', 'loadedSessionEvents']],
        actions: [
            sessionsTableLogic,
            ['fetchNextSessions', 'appendNewSessions', 'closeSessionPlayer', 'loadSessionEvents'],
        ],
    },
    actions: {
        toggleAddingTagShown: () => {},
        setAddingTag: (payload: string) => ({ payload }),
        goToNext: true,
        goToPrevious: true,
        openNextRecordingOnLoad: true,
        setSource: (source: RecordingWatchedSource) => ({ source }),
        reportUsage: (recordingData: SessionPlayerData, loadTime: number) => ({ recordingData, loadTime }),
        loadRecording: (sessionRecordingId?: string, url?: string) => ({ sessionRecordingId, url }),
        loadEvents: (url?: string) => ({ url }),
    },
    reducers: {
        sessionRecordingId: [
            null as SessionRecordingId | null,
            {
                loadRecording: (_, { sessionRecordingId }) => sessionRecordingId ?? null,
            },
        ],
        addingTagShown: [
            false,
            {
                toggleAddingTagShown: (state) => !state,
            },
        ],
        addingTag: [
            '',
            {
                setAddingTag: (_, { payload }) => payload,
            },
        ],
        loadingNextRecording: [
            false,
            {
                openNextRecordingOnLoad: () => true,
                loadRecording: () => false,
                closeSessionPlayer: () => false,
            },
        ],
        chunkIndex: [
            0,
            {
                loadRecordingSuccess: (state) => state + 1,
            },
        ],
        sessionPlayerDataLoading: [
            false,
            {
                loadRecordingSuccess: (_, { sessionPlayerData }) => {
                    // If sessionPlayerData doesn't have a next url, it means the entire recording is still loading.
                    return !!sessionPlayerData?.next
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
    listeners: ({ values, actions }) => ({
        toggleAddingTagShown: () => {
            // Clear text when tag input is dismissed
            if (!values.addingTagShown) {
                actions.setAddingTag('')
            }
        },
        goToNext: () => {
            if (values.recordingIndex < values.orderedSessionRecordingIds.length - 1) {
                const id = values.orderedSessionRecordingIds[values.recordingIndex + 1]
                actions.loadRecording(id)
            } else if (values.pagination) {
                // :TRICKY: Load next page of sessions, which will call appendNewSessions which will call goToNext again
                actions.openNextRecordingOnLoad()
                actions.fetchNextSessions()
            } else {
                toast('Found no more recordings.', { type: 'info' })
            }
        },
        goToPrevious: () => {
            const id = values.orderedSessionRecordingIds[values.recordingIndex - 1]
            actions.loadRecording(id)
        },
        appendNewSessions: () => {
            if (values.sessionRecordingId && values.loadingNextRecording) {
                actions.goToNext()
            }
        },
        loadRecordingSuccess: () => {
            // If there is more data to poll for load the next batch.
            // This will keep calling loadRecording until `next` is empty.
            if (!!values.sessionPlayerData?.next) {
                actions.loadRecording(undefined, values.sessionPlayerData.next)
            }
            // TODO: Move this to loadMetadataSuccess when endpoints for metadata and snapshots are split
            // Fetch events as soon as frontend gets metadata.
            if (values.chunkIndex === 1 && values.eventsApiParams) {
                actions.loadEvents()
            }
        },
        loadRecordingFailure: ({ error }) => {
            errorToast('Error fetching your session recording', 'The following error message was returned:', error)
        },
        loadEventsSuccess: () => {
            // Poll next events
            if (!!values.sessionEvents?.next) {
                actions.loadEvents(values.sessionEvents.next)
            }
        },
        loadEventsFailure: ({ error }) => {
            errorToast(
                'Error fetching events for this session recording',
                'The following error message was returned:',
                error
            )
        },
        recordUsage: async ({ recordingData, loadTime }, breakpoint) => {
            await breakpoint()
            eventUsageLogic.actions.reportRecordingViewed(recordingData, values.source, loadTime, 0)
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportRecordingViewed(recordingData, values.source, loadTime, 10)
        },
    }),
    loaders: ({ values, actions }) => ({
        tags: [
            ['activating', 'watched', 'deleted'] as string[],
            {
                createTag: async () => {
                    const newTag = [values.addingTag]
                    const promise = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 3000)) // TODO: Temp to simulate loading
                    await promise()

                    actions.toggleAddingTagShown()
                    return values.tags.concat(newTag)
                },
            },
        ],
        sessionPlayerData: [
            {} as SessionPlayerData,
            {
                loadRecording: async ({ sessionRecordingId, url }): Promise<SessionPlayerData> => {
                    const startTime = performance.now()

                    // Use `url` if there is a `next` url to fetch
                    const apiUrl =
                        url ||
                        `api/event/session_recording?${toParams({
                            session_recording_id: sessionRecordingId,
                            save_view: true,
                        })}`
                    const response = await api.get(apiUrl)

                    // Record recording viewed on very first call
                    if (!url) {
                        actions.reportUsage(response.result, performance.now() - startTime)
                    }
                    return {
                        ...response.result,
                        snapshots: [
                            ...(values.sessionPlayerData?.snapshots ?? []),
                            ...(response.result?.snapshots ?? []),
                        ],
                    }
                },
            },
        ],
        sessionEvents: [
            {} as SessionRecordingEvents,
            {
                loadEvents: async ({ url }) => {
                    if (!values.eventsApiParams) {
                        return values.sessionEvents
                    }
                    const startTime = performance.now()

                    console.log('LOADEVENTS', values.eventsApiParams)

                    // Use `url` if there is a `next` url to fetch
                    const apiUrl = url || `api/event/?${toParams(values.eventsApiParams)}`
                    const response = await api.get(apiUrl)

                    eventUsageLogic.actions.reportRecordingEventsFetched(
                        response.results.length ?? 0,
                        performance.now() - startTime
                    )

                    return {
                        ...values.sessionEvents,
                        events: [...(values.sessionEvents?.events ?? []), ...(response.results ?? [])],
                    }
                },
            },
        ],
    }),
    selectors: {
        sessionDate: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData: SessionPlayerData): string | null => {
                if (!sessionPlayerData?.start_time) {
                    return null
                }
                return dayjs(sessionPlayerData.start_time).format('MMM Do')
            },
        ],
        eventIndex: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData: SessionPlayerData): EventIndex => new EventIndex(sessionPlayerData?.snapshots || []),
        ],
        recordingIndex: [
            (selectors) => [selectors.orderedSessionRecordingIds, selectors.sessionRecordingId],
            (recordingIds: SessionRecordingId[], id: SessionRecordingId): number => recordingIds.indexOf(id),
        ],
        showPrev: [(selectors) => [selectors.recordingIndex], (index: number): boolean => index > 0],
        showNext: [
            (selectors) => [selectors.recordingIndex, selectors.orderedSessionRecordingIds, selectors.pagination],
            (index: number, ids: SessionRecordingId[], pagination: Record<string, any> | null) =>
                index > -1 && (index < ids.length - 1 || pagination !== null),
        ],
        session: [
            (selectors) => [selectors.sessionRecordingId, selectors.sessions],
            (id: SessionRecordingId, sessions: Array<SessionType>): SessionType | null => {
                const [session] = sessions.filter(
                    (s) => s.session_recordings.filter((recording) => id === recording.id).length > 0
                )
                return session
            },
        ],
        shouldLoadSessionEvents: [
            (selectors) => [selectors.session, selectors.loadedSessionEvents],
            (session, sessionEvents) => session && !sessionEvents[session.global_session_id],
        ],
        firstChunkLoaded: [(selectors) => [selectors.chunkIndex], (chunkIndex) => chunkIndex > 0],
        isPlayable: [
            (selectors) => [
                selectors.firstChunkLoaded,
                selectors.sessionPlayerDataLoading,
                selectors.sessionPlayerData,
            ],
            (firstChunkLoaded, sessionPlayerDataLoading, sessionPlayerData) =>
                (firstChunkLoaded || // If first chunk is ready
                    !sessionPlayerDataLoading) && // data isn't being fetched
                sessionPlayerData?.snapshots.length >= 2 && // more than two snapshots needed to init Replayed
                !!sessionPlayerData?.snapshots?.find((s: eventWithTime) => s.type === 2), // there's a full snapshot in the data that was loaded
        ],
        highlightedSessionEvents: [
            (selectors) => [selectors.session, selectors.loadedSessionEvents],
            (session, sessionEvents) => {
                if (!session) {
                    return []
                }
                const events = sessionEvents[session.global_session_id] || []
                return events.filter((e) => (session.matching_events || []).includes(e.id))
            },
        ],
        shownPlayerEvents: [
            (selectors) => [selectors.sessionPlayerData, selectors.eventIndex, selectors.highlightedSessionEvents],
            (sessionPlayerData, eventIndex, events) => {
                if (!sessionPlayerData) {
                    return []
                }
                const startTime = +dayjs(sessionPlayerData.start_time)

                const pageChangeEvents = eventIndex.pageChangeEvents().map(({ playerTime, href }) => ({
                    playerTime,
                    text: href,
                    color: 'blue',
                }))
                const highlightedEvents = events.map((event) => ({
                    playerTime: +dayjs(event.timestamp) - startTime,
                    text: eventToName(event),
                    color: 'orange',
                }))

                return pageChangeEvents.concat(highlightedEvents).sort((a, b) => a.playerTime - b.playerTime)
            },
        ],
        eventsApiParams: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => {
                // TODO: This will change when session endpoint is separated into metadata and snapshots endpoints
                // For now we pull person and timestamp data from the metadata returned from /api/session_recording
                if (!sessionPlayerData?.person?.id || !sessionPlayerData?.start_time || !sessionPlayerData?.duration) {
                    return null
                }

                const buffer_ms = sessionPlayerData?.duration / 4 // +- before and after start and end of a recording to query for.
                return {
                    person_id: sessionPlayerData?.person?.id,
                    after: dayjs.utc(sessionPlayerData?.start_time).subtract(buffer_ms, 'ms').format(),
                    before: dayjs
                        .utc(sessionPlayerData?.start_time)
                        .add(buffer_ms + sessionPlayerData?.duration, 'ms')
                        .format(),
                }
            },
        ],
    },
    urlToAction: ({ actions, values }) => {
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
                actions.loadRecording(sessionRecordingId)
            }
        }

        return {
            '/sessions': urlToAction,
            '/recordings': urlToAction,
            '/person/*': urlToAction,
        }
    },
})
