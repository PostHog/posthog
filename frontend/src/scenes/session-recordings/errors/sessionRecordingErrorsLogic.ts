import { actions, afterMount, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import { ErrorClusterResponse } from '~/types'

import { createPlaylist } from '../playlist/playlistUtils'
import type { sessionRecordingErrorsLogicType } from './sessionRecordingErrorsLogicType'

export const sessionRecordingErrorsLogic = kea<sessionRecordingErrorsLogicType>([
    path(['scenes', 'session-recordings', 'detail', 'sessionRecordingErrorsLogic']),
    actions({
        createPlaylist: (name: string, sessionIds: string[]) => ({ name, sessionIds }),
    }),
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
    listeners(() => ({
        createPlaylist: async ({ name, sessionIds }) => {
            const playlist = await createPlaylist({ name: name })

            if (playlist) {
                const samples = sessionIds.slice(0, 10)
                await Promise.all(
                    samples.map((sessionId) => api.recordings.addRecordingToPlaylist(playlist.short_id, sessionId))
                )
                router.actions.push(urls.replayPlaylist(playlist.short_id))
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadErrorClusters(false)
    }),
])
