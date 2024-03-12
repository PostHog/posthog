import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { ErrorClusterResponse } from '~/types'

import type { sessionRecordingErrorsLogicType } from './sessionRecordingErrorsLogicType'

export const sessionRecordingErrorsLogic = kea<sessionRecordingErrorsLogicType>([
    path(['scenes', 'session-recordings', 'detail', 'sessionRecordingErrorsLogic']),
    loaders(() => ({
        errors: [
            null as ErrorClusterResponse,
            {
                loadErrorClusters: async (refresh: boolean = true) => {
                    const response = await api.recordings.errorClusters(refresh)
                    return response
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadErrorClusters(false)
    }),
])
