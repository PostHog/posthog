import { kea } from 'kea'
import { eventWithTime } from 'rrweb/typings/types'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { sessionsPlayLogicType } from 'types/scenes/sessions/sessionsPlayLogicType'
import { PersonType } from '~/types'
import moment from 'moment'
import { EventIndex } from 'posthog-react-rrweb-player'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { toast } from 'react-toastify'

type SessionRecordingId = string

interface SessionPlayerData {
    snapshots: eventWithTime[]
    person: PersonType | null
}

export const sessionsPlayLogic = kea<sessionsPlayLogicType<SessionPlayerData, EventIndex>>({
    connect: {
        values: [sessionsTableLogic, ['sessions', 'nextOffset', 'orderedSessionRecordingIds']],
        actions: [sessionsTableLogic, ['fetchNextSessions', 'appendNewSessions', 'closeSessionPlayer']],
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
            } else if (values.nextOffset) {
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
    urlToAction: ({ actions, values }) => ({
        '*': (_: any, params: { sessionRecordingId: SessionRecordingId }) => {
            const sessionRecordingId = params.sessionRecordingId
            if (sessionRecordingId !== values.sessionRecordingId && sessionRecordingId) {
                actions.loadRecording(sessionRecordingId)
            }
        },
    }),
    loaders: ({ values, actions }) => ({
        tags: [
            ['activating', 'watched', 'deleted'] as string[], // TODO: Temp values for testing
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
                const params = toParams({ session_recording_id: sessionRecordingId })
                const response = await api.get(`api/event/session_recording?${params}`)
                return response.result
            },
        },
    }),
    selectors: {
        sessionDate: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData: SessionPlayerData): string | null => {
                if (!sessionPlayerData?.snapshots.length || !sessionPlayerData.snapshots[0].timestamp) {
                    return null
                }
                // :KLUDGE: This is not using the session timestamp but client-side timestamp
                return moment(sessionPlayerData.snapshots[0].timestamp).format('MMM Do')
            },
        ],
        eventIndex: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData: SessionPlayerData): EventIndex => new EventIndex(sessionPlayerData?.snapshots || []),
        ],
        pageVisitEvents: [(selectors) => [selectors.eventIndex], (eventIndex) => eventIndex.pageChangeEvents()],
        recordingIndex: [
            (selectors) => [selectors.orderedSessionRecordingIds, selectors.sessionRecordingId],
            (recordingIds: SessionRecordingId[], id: SessionRecordingId): number => recordingIds.indexOf(id),
        ],
        showPrev: [(selectors) => [selectors.recordingIndex], (index: number): boolean => index > 0],
        showNext: [
            (selectors) => [selectors.recordingIndex, selectors.orderedSessionRecordingIds, selectors.nextOffset],
            (index: number, ids: SessionRecordingId[], offset: number | null) =>
                index > -1 && (index < ids.length - 1 || offset !== null),
        ],
    },
})
