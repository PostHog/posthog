import { actions, afterMount, kea, key, path, props, selectors } from 'kea'
import { Breadcrumb, SessionRecordingPlaylistType, SessionRecordingsTabs } from '~/types'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'
import { urls } from 'scenes/urls'

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

    selectors(({}) => ({
        breadcrumbs: [
            (s) => [s.playlist],
            (playlist): Breadcrumb[] => [
                {
                    name: 'Recording Playlists',
                    path: urls.sessionRecordings(SessionRecordingsTabs.All),
                },
                {
                    name: playlist?.name || 'Untitled Playlist',
                    path: urls.sessionRecordingPlaylist(playlist?.short_id || ''),
                },
            ],
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadPlaylist()
    }),
])
