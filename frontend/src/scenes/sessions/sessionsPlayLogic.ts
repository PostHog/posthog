import { kea } from 'kea'
import { eventWithTime } from 'rrweb/typings/types'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { sessionsPlayLogicType } from 'types/scenes/sessions/sessionsPlayLogicType'
import { PersonType } from '~/types'
import moment from 'moment'
interface SessionPlayerData {
    snapshots: eventWithTime[]
    person: PersonType | null
}

export const sessionsPlayLogic = kea<sessionsPlayLogicType<SessionPlayerData>>({
    actions: {
        toggleAddingTagShown: () => {},
        setAddingTag: (payload: string) => ({ payload }),
    },
    reducers: {
        sessionRecordingId: [
            null as string | null,
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
    },
    listeners: ({ values, actions }) => ({
        toggleAddingTagShown: () => {
            // Clear text when tag input is dismissed
            if (!values.addingTagShown) {
                actions.setAddingTag('')
            }
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '*': (_: any, params: { id: string }) => {
            const sessionRecordingId = params.id
            if (sessionRecordingId !== values.sessionRecordingId) {
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
        sessionTimestamp: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData: SessionPlayerData): string | null => {
                if (!sessionPlayerData?.snapshots.length || !sessionPlayerData.snapshots[0].timestamp) {
                    return null
                }
                // TODO: Client-side timestamp, needs review
                return moment(sessionPlayerData.snapshots[0].timestamp).format('lll')
            },
        ],
    },
})
