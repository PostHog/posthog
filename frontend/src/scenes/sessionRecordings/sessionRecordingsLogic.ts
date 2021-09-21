import { kea } from 'kea'
import api from 'lib/api'

import { SessionRecordingType } from '~/types'
import { sessionRecordingsTableLogicType } from './sessionRecordingsLogicType'

export const sessionRecordingsTableLogic = kea<sessionRecordingsTableLogicType>({
    actions: {
        getSessionRecordings: true,
    },
    loaders: () => ({
        sessionRecordings: [
            [] as SessionRecordingType[],
            {
                getSessionRecordings: async () => {
                    const response = await api.get(`api/projects/@current/session_recordings`)
                    return response.results
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.getSessionRecordings()
        },
    }),
})
