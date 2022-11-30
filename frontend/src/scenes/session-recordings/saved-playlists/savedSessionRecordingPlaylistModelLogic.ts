import { actions, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { SessionRecordingPlaylistType, SessionRecordingType } from '~/types'
import type { savedSessionRecordingPlaylistModelLogicType } from './savedSessionRecordingPlaylistModelLogicType'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'
import { deleteWithUndo, toParams } from 'lib/utils'
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
        loadSavedPlaylist: (shortId: SessionRecordingPlaylistType['short_id']) => ({ shortId }),
        createSavedPlaylist: (playlist: Partial<SessionRecordingPlaylistType>, redirect: boolean = false) => ({
            playlist,
            redirect,
        }),
        duplicateSavedPlaylist: (playlist: Partial<SessionRecordingPlaylistType>, redirect: boolean = false) => ({
            playlist,
            redirect,
        }),
        updateSavedPlaylist: (playlist: PlaylistTypeWithShortId, silent = false) => ({ playlist, silent }),
        deleteSavedPlaylistWithUndo: (playlist: PlaylistTypeWithShortId, undoCallback?: () => void) => ({
            playlist,
            undoCallback,
        }),
        addRecordingToPlaylist: (
            recording: RecordingTypeWithIdAndPlaylist,
            playlist: PlaylistTypeWithIds,
            silent = false
        ) => ({ recording, playlist, silent }),
        removeRecordingFromPlaylist: (
            recording: RecordingTypeWithIdAndPlaylist,
            playlist: PlaylistTypeWithIds,
            silent = false
        ) => ({ recording, playlist, silent }),
    })),
    loaders(() => ({
        _playlistModel: {
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
        _recordingModel: {
            addRecordingToPlaylist: async ({ recording, playlist, silent }) => {
                const newRecordingResponse = await api.recordings.updateRecording(
                    recording.id,
                    {
                        playlists: [...(recording.playlists || []).filter((id) => id !== playlist.id), playlist.id],
                    },
                    toParams({
                        recording_start_time: recording.start_time,
                    })
                )
                if (!silent) {
                    lemonToast.success('Recording added to playlist', {
                        button: {
                            label: 'View playlist',
                            action: () => router.actions.push(urls.sessionRecordingPlaylist(playlist.short_id)),
                        },
                    })
                }
                return newRecordingResponse.result.session_recording
            },
            removeRecordingFromPlaylist: async ({ recording, playlist, silent }) => {
                const newRecordingResponse = await api.recordings.updateRecording(
                    recording.id,
                    {
                        playlists: [...(recording.playlists || []).filter((id) => id !== playlist.id)],
                    },
                    toParams({
                        recording_start_time: recording.start_time,
                    })
                )
                if (!silent) {
                    lemonToast.success('Recording removed from playlist')
                }
                return newRecordingResponse.result.session_recording
            },
        },
    })),
])
