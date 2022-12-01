import { kea, props, path, key, actions, reducers, selectors, afterMount, listeners, connect } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import {
    createPlaylist,
    PlaylistTypeWithIds,
} from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import type { playlistPopupLogicType } from './playlistPopupLogicType'
import { SessionRecordingPlaylistType } from '~/types'
import { forms } from 'kea-forms'

export const playlistPopupLogic = kea<playlistPopupLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playlist-popup', 'playlistPopupLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        actions: [sessionRecordingPlayerLogic(props), ['setPause']],
    })),
    actions(() => ({
        setSearchQuery: (query: string) => ({ query }),
        addToPlaylist: (playlist: PlaylistTypeWithIds) => ({ playlist }),
        removeFromPlaylist: (playlist: PlaylistTypeWithIds) => ({ playlist }),
        loadPlaylists: true,
        setNewFormShowing: (show: boolean) => ({ show }),
        setShowPlaylistPopup: (show: boolean) => ({ show }),
    })),
    loaders(({ values }) => ({
        playlists: {
            __default: [] as SessionRecordingPlaylistType[],
            loadPlaylists: async (_, breakpoint) => {
                await breakpoint(300)
                const response = await api.recordings.listPlaylists(
                    toParams({ static: true, search: values.searchQuery })
                )
                breakpoint()
                return response.results
            },
        },
    })),
    reducers(() => ({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        newFormShowing: [
            false,
            {
                setNewFormShowing: (_, { show }) => show,
            },
        ],
        showPlaylistPopup: [
            false,
            {
                setShowPlaylistPopup: (_, { show }) => show,
            },
        ],
    })),
    forms(({ actions }) => ({
        newPlaylist: {
            defaults: { name: '' },
            errors: ({ name }) => ({
                name: !name ? 'Required' : null,
            }),
            submit: async ({ name }, breakpoint) => {
                await breakpoint(100)
                const newPlaylist = await createPlaylist({
                    name,
                    is_static: true,
                })
                breakpoint()

                if (!newPlaylist) {
                    // This indicates the billing popup has been shown so we should close the modal

                    actions.setShowPlaylistPopup(false)
                    return
                }

                actions.setNewFormShowing(false)
                actions.resetNewPlaylist()
                actions.loadPlaylists()
            },
        },
    })),
    listeners(({ actions, values }) => ({
        setSearchQuery: () => {
            actions.loadPlaylists()
        },
        setNewFormShowing: ({ show }) => {
            if (show) {
                actions.setNewPlaylistValue('name', values.searchQuery)
            }
        },

        setShowPlaylistPopup: ({ show }) => {
            if (show) {
                actions.loadPlaylists()
                actions.setPause()
            }
        },

        // addToPlaylist: async ({ playlist, recording }) => {
        //     const newRecordingResponse = await api.recordings.updateRecording(
        //         recording.id,
        //         {
        //             playlists: [...(recording.playlists || []).filter((id) => id !== playlist.id), playlist.id],
        //         },
        //         toParams({
        //             recording_start_time: recording.start_time,
        //         })
        //     )
        //     return newRecordingResponse.result.session_recording
        // },
        // addRecordingToPlaylistSuccess: ({ _recordingModel, payload }) => {
        //     if (_recordingModel.playlists) {
        //         actions.setRecordingMeta({
        //             metadata: {
        //                 ...values.sessionPlayerMetaData.metadata,
        //                 playlists: [..._recordingModel.playlists],
        //             },
        //         })
        //         // Update playlist if playlist detail page is mounted
        //         payload?.playlist?.short_id &&
        //             sessionRecordingsPlaylistLogic
        //                 .findMounted({ shortId: payload.playlist.short_id })
        //                 ?.actions?.getPlaylist()
        //     }
        // },
        // removeFromPlaylist: async ({ playlist }) => {
        //     actions.removeRecordingFromPlaylist(
        //         {
        //             id: props.sessionRecordingId,
        //             playlists: values.recordingPlaylists,
        //         },
        //         playlist
        //     )
        // },
        // removeRecordingFromPlaylistSuccess: ({ _recordingModel, payload }) => {
        //     if (_recordingModel.playlists) {
        //         actions.setRecordingMeta({
        //             metadata: {
        //                 ...values.sessionPlayerMetaData.metadata,
        //                 playlists: [..._recordingModel.playlists],
        //             },
        //         })
        //         // Update playlist if playlist detail page is mounted
        //         payload?.playlist?.short_id &&
        //             sessionRecordingsPlaylistLogic
        //                 .findMounted({ shortId: payload.playlist.short_id })
        //                 ?.actions?.getPlaylist()
        //     }
        // },
    })),
    selectors(() => ({})),
])
