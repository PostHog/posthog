import { actions, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { SessionRecordingPlaylistType } from '~/types'
import type { savedSessionRecordingPlaylistModelLogicType } from './savedSessionRecordingPlaylistModelLogicType'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'
import { deleteWithUndo } from 'lib/utils'
import { DEFAULT_RECORDING_FILTERS } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { openBillingPopupModal } from 'scenes/billing/v2/BillingPopup'
import { PLAYLIST_LIMIT_REACHED_MESSAGE } from 'scenes/session-recordings/sessionRecordingsLogic'

async function createPlaylist(
    playlist: Partial<SessionRecordingPlaylistType>,
    redirect = false
): Promise<SessionRecordingPlaylistType | null> {
    try {
        playlist.filters = playlist.filters || DEFAULT_RECORDING_FILTERS
        const res = await api.recordings.createPlaylist(playlist)
        if (redirect) {
            router.actions.push(urls.sessionRecordingPlaylist(res.short_id))
        }
        return res
    } catch (e: any) {
        if (e.status === 403) {
            openBillingPopupModal({
                title: `Upgrade now to unlock unlimited playlists`,
                description: PLAYLIST_LIMIT_REACHED_MESSAGE,
            })
        } else {
            throw e
        }
    }

    return null
}

// Logic that encapsulates all saved recording playlist CRUD actions
export const savedSessionRecordingPlaylistModelLogic = kea<savedSessionRecordingPlaylistModelLogicType>([
    path(['scenes', 'session-recordings', 'saved-playlists', 'savedSessionRecordingPlaylistModelLogic']),
    actions(() => ({
        loadSavedPlaylist: (shortId: SessionRecordingPlaylistType['short_id']) => ({ shortId }),
        createSavedPlaylist: (playlist: Partial<SessionRecordingPlaylistType>, redirect: boolean = false) => ({
            playlist,
            redirect,
        }),
        duplicateSavedPlaylist: (playlist: Partial<SessionRecordingPlaylistType>, redirect: boolean = false) => ({
            playlist,
            redirect,
        }),
        updateSavedPlaylist: (
            shortId: SessionRecordingPlaylistType['short_id'],
            playlist: Partial<SessionRecordingPlaylistType>,
            silent = false
        ) => ({ shortId, playlist, silent }),
        deleteSavedPlaylistWithUndo: (playlist: SessionRecordingPlaylistType, undoCallback?: () => void) => ({
            playlist,
            undoCallback,
        }),
    })),
    loaders(() => ({
        _savedPlaylist: {
            loadSavedPlaylist: async ({ shortId }) => {
                return api.recordings.getPlaylist(shortId)
            },
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
                partialPlaylist.derived_name = partialPlaylist.derived_name

                const newPlaylist = await createPlaylist(playlist, redirect)
                breakpoint()
                if (!newPlaylist) {
                    return null
                }

                lemonToast.success('Playlist duplicated successfully')

                return newPlaylist
            },
            updateSavedPlaylist: async ({ shortId, playlist, silent }, breakpoint) => {
                await breakpoint(100)
                const newPlaylist = await api.recordings.updatePlaylist(shortId, playlist)
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
