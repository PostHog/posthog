import { actions, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { SessionRecordingPlaylistType, SessionRecordingType } from '~/types'
import type { savedSessionRecordingPlaylistModelLogicType } from './savedSessionRecordingPlaylistModelLogicType'
import { lemonToast } from 'lib/components/lemonToast'
import { createPlaylist } from 'scenes/session-recordings/playlist/playlistUtils'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils'

export type PlaylistTypeWithShortId = Partial<SessionRecordingPlaylistType> &
    Pick<SessionRecordingPlaylistType, 'short_id'>
export type PlaylistTypeWithIds = PlaylistTypeWithShortId & Pick<SessionRecordingPlaylistType, 'id'>
export type RecordingTypeWithIdAndPlaylist = Partial<SessionRecordingType> &
    Pick<SessionRecordingType, 'id' | 'playlists'>
export interface UpdatedRecordingResponse {
    result: {
        session_recording: RecordingTypeWithIdAndPlaylist
    }
}

// Logic that encapsulates all saved recording playlist CRUD actions
export const savedSessionRecordingPlaylistModelLogic = kea<savedSessionRecordingPlaylistModelLogicType>([
    path(['scenes', 'session-recordings', 'saved-playlists', 'savedSessionRecordingPlaylistModelLogic']),
    actions(() => ({
        createSavedPlaylist: (playlist: Partial<SessionRecordingPlaylistType>, redirect: boolean = false) => ({
            playlist,
            redirect,
        }),
        duplicateSavedPlaylist: (playlist: Partial<SessionRecordingPlaylistType>, redirect: boolean = false) => ({
            playlist,
            redirect,
        }),
    })),
    loaders(() => ({
        _playlistModel: {
            createSavedPlaylist: async ({ playlist, redirect }, breakpoint) => {
                await breakpoint(100)
                const newPlaylist = await createPlaylist(playlist, redirect)
                breakpoint()
                return newPlaylist
            },
            duplicateSavedPlaylist: async ({ playlist, redirect }, breakpoint) => {
                await breakpoint(100)

                const { id, short_id, ...partialPlaylist } = playlist
                partialPlaylist.name = partialPlaylist.name ? partialPlaylist.name + ' (copy)' : ''

                const newPlaylist = await createPlaylist(partialPlaylist, redirect)
                breakpoint()
                if (!newPlaylist) {
                    return null
                }

                lemonToast.success('Playlist duplicated successfully')

                return newPlaylist
            },
            updateSavedPlaylist: async ({ playlist, silent }, breakpoint) => {
                await breakpoint(100)
                const newPlaylist = await api.recordings.updatePlaylist(playlist.short_id, playlist)
                breakpoint()

                if (!silent) {
                    lemonToast.success('Playlist updated successfully')
                }

                return newPlaylist
            },
            deleteSavedPlaylistWithUndo: async ({ playlist, undoCallback }) => {
                await deleteWithUndo({
                    object: playlist,
                    idField: 'short_id',
                    endpoint: `projects/@current/session_recording_playlists`,
                    callback: undoCallback,
                })
                return playlist
            },
        },
    })),
])
