import { kea } from 'kea'
import { eventWithTime } from 'rrweb/typings/types'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { sessionsPlayLogicType } from 'types/scenes/sessions/sessionsPlayLogicType'

export const sessionsPlayLogic = kea<sessionsPlayLogicType<eventWithTime>>({
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
            null as null | eventWithTime[],
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
        '*': (_: any, params: { sessionRecordingId: string }) => {
            const sessionRecordingId = params.sessionRecordingId
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
            loadRecording: async (sessionRecordingId: string): Promise<eventWithTime[]> => {
                const params = toParams({ session_recording_id: sessionRecordingId })
                const response = await api.get(`api/event/session_recording?${params}`)
                console.log('loadRecording', response.result)
                return response.result
            },
        },
    }),
})
