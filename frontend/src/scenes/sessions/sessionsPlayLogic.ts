import { kea } from 'kea'
import { eventWithTime } from 'rrweb/typings/types'
import api from 'lib/api'
import { eventToName, toParams } from 'lib/utils'
import { sessionsPlayLogicType } from './sessionsPlayLogicType'
import { PersonType, SessionType } from '~/types'
import dayjs from 'dayjs'
import { EventIndex } from '@posthog/react-rrweb-player'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { toast } from 'react-toastify'

type SessionRecordingId = string

interface SessionPlayerData {
    snapshots: eventWithTime[]
    person: PersonType | null
    start_time: string
}

export const sessionsPlayLogic = kea<sessionsPlayLogicType<SessionPlayerData, SessionRecordingId>>({
    connect: {
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
    },
    reducers: {
        sessionRecordingId: [
            null as SessionRecordingId | null,
            {
                loadRecording: (_, sessionRecordingId) => sessionRecordingId,
            },
        ],
        sessionPlayerData: [
            null as null | SessionPlayerData,
            {
                loadRecording: () => null,
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
            loadRecording: async (sessionRecordingId: string): Promise<SessionPlayerData> => {
                const params = toParams({ session_recording_id: sessionRecordingId, save_view: true })
                const response = await api.get(`api/event/session_recording?${params}`)
                return response.result
            },
        },
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
    },
    urlToAction: ({ actions, values }) => {
        const urlToAction = (
            _: any,
            params: {
                sessionRecordingId?: SessionRecordingId
            }
        ): void => {
            const sessionRecordingId = params.sessionRecordingId
            if (values && sessionRecordingId !== values.sessionRecordingId && sessionRecordingId) {
                actions.loadRecording(sessionRecordingId)
            }
        }

        return {
            '/sessions': urlToAction,
            '/session_recordings': urlToAction,
            '/person/*': urlToAction,
        }
    },
})
