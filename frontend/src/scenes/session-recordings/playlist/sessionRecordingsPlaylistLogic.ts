import { actions, afterMount, kea, key, path, props } from 'kea'
import { SessionRecordingPlaylistType } from '~/types'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'

export interface SessionRecordingsPlaylistLogicProps {
    shortId: string
}

export const sessionRecordingsPlaylistLogic = kea<sessionRecordingsPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsPlaylistLogic', key]),
    props({} as SessionRecordingsPlaylistLogicProps),
    key((props) => props.shortId),
    actions({
        loadPlaylist: true,
    }),
    loaders(({ props }) => ({
        playlist: [
            null as SessionRecordingPlaylistType | null,
            {
                loadPlaylist: async (_, breakpoint) => {
                    breakpoint(100)
                    return api.recordings.getPlaylist(props.shortId)
                },

                updatePlaylist: async (playlist: Partial<SessionRecordingPlaylistType>, breakpoint) => {
                    breakpoint(100)
                    return api.recordings.updatePlaylist(props.shortId, playlist)
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadPlaylist()
    }),
])
