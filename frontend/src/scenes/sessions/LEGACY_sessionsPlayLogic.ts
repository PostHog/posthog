import { kea } from 'kea'
import api from 'lib/api'
import { errorToast, eventToName, toParams } from 'lib/utils'
import {
    LEGACY_SessionPlayerData,
    SessionPlayerData,
    SessionRecordingId,
    SessionRecordingUsageType,
    SessionType,
} from '~/types'
import dayjs from 'dayjs'
import { LEGACY_sessionsPlayLogicType } from './LEGACY_sessionsPlayLogicType'
import { EventIndex } from '@posthog/react-rrweb-player'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { toast } from 'react-toastify'
import { eventUsageLogic, RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { teamLogic } from '../teamLogic'
import { eventWithTime } from 'rrweb/typings/types'
const IS_TEST_MODE = process.env.NODE_ENV === 'test'

const convertToNewSessionPlayerDataType = (legacyData: LEGACY_SessionPlayerData): SessionPlayerData => {
    return {
        snapshots: legacyData?.snapshots,
        person: legacyData?.person,
        session_recording: {
            id: `${legacyData?.person?.id}` ?? 'legacy_recording_id',
            viewed: true,
            recording_duration: legacyData?.duration,
            start_time: +dayjs(legacyData?.start_time),
            end_time: +dayjs(legacyData?.start_time) + legacyData?.duration,
            distinct_id: legacyData?.person?.distinct_ids[0] ?? `${legacyData?.person?.id}`,
        },
    }
}

export const LEGACY_sessionsPlayLogic = kea<LEGACY_sessionsPlayLogicType>({
    connect: {
        logic: [eventUsageLogic],
        values: [
            sessionsTableLogic,
            ['sessions', 'pagination', 'orderedSessionRecordingIds', 'loadedSessionEvents'],
            teamLogic,
            ['currentTeamId'],
        ],
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
        reportUsage: (recordingData: LEGACY_SessionPlayerData, loadTime: number) => ({ recordingData, loadTime }),
        loadRecording: (sessionRecordingId?: string, url?: string) => ({ sessionRecordingId, url }),
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
        loadRecordingSuccess: async () => {
            // If there is more data to poll for load the next batch.
            // This will keep calling loadRecording until `next` is empty.
            if (!!values.sessionPlayerData?.next) {
                await actions.loadRecording(undefined, values.sessionPlayerData.next)
            }
        },
        loadRecordingFailure: ({ error }) => {
            errorToast(
                'Error fetching your session recording',
                'Your recording returned the following error response:',
                error
            )
        },
        reportUsage: async ({ recordingData, loadTime }, breakpoint) => {
            await breakpoint()
            eventUsageLogic.actions.reportRecording(
                convertToNewSessionPlayerDataType(recordingData),
                values.source,
                loadTime,
                SessionRecordingUsageType.VIEWED,
                0
            )
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportRecording(
                convertToNewSessionPlayerDataType(recordingData),
                values.source,
                loadTime,
                SessionRecordingUsageType.ANALYZED,
                10
            )
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
        sessionPlayerData: {
            loadRecording: async ({ sessionRecordingId, url }): Promise<LEGACY_SessionPlayerData> => {
                const startTime = performance.now()

                let response
                if (url) {
                    // Subsequent calls to get rest of recording
                    response = await api.get(url)
                } else {
                    // Very first call
                    const params = toParams({ session_recording_id: sessionRecordingId, save_view: true })
                    response = await api.get(`api/projects/${values.currentTeamId}/events/session_recording?${params}`)
                    actions.reportUsage(response.result, performance.now() - startTime)
                }
                const currData = values.sessionPlayerData
                return {
                    ...response.result,
                    snapshots: [...(currData?.snapshots ?? []), ...(response.result?.snapshots ?? [])],
                }
            },
        },
    }),
    selectors: {
        sessionDate: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData: LEGACY_SessionPlayerData): string | null => {
                if (!sessionPlayerData?.start_time) {
                    return null
                }
                return dayjs(sessionPlayerData.start_time).format('MMM Do')
            },
        ],
        eventIndex: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData: LEGACY_SessionPlayerData): EventIndex =>
                new EventIndex(sessionPlayerData?.snapshots || []),
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
                return [...pageChangeEvents, ...highlightedEvents].sort((a, b) => a.playerTime - b.playerTime)
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
