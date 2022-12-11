import { kea, props, path, key, actions, reducers, selectors, listeners, connect } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { createPlaylist } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import type { playlistPopupLogicType } from './playlistPopupLogicType'
import { SessionRecordingPlaylistType } from '~/types'
import { forms } from 'kea-forms'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'

export const playlistPopupLogic = kea<playlistPopupLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playlist-popup', 'playlistPopupLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        actions: [sessionRecordingPlayerLogic(props), ['setPause']],
    })),
    actions(() => ({
        setSearchQuery: (query: string) => ({ query }),
        loadPlaylists: true,
        loadPlaylistsForRecording: true,
        addToPlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
        removeFromPlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
        setNewFormShowing: (show: boolean) => ({ show }),
        setShowPlaylistPopup: (show: boolean) => ({ show }),
    })),
    loaders(({ values, props }) => ({
        playlists: {
            __default: [] as SessionRecordingPlaylistType[],
            loadPlaylists: async (_, breakpoint) => {
                await breakpoint(300)
                const response = await api.recordings.listPlaylists(toParams({ search: values.searchQuery }))
                breakpoint()
                return response.results
            },
        },
        currentPlaylists: {
            __default: [] as SessionRecordingPlaylistType[],
            loadPlaylistsForRecording: async (_, breakpoint) => {
                await breakpoint(300)
                const response = await api.recordings.listPlaylists(
                    toParams({ session_recording_id: props.sessionRecordingId })
                )
                breakpoint()
                return response.results
            },

            addToPlaylist: async ({ playlist }) => {
                await api.recordings.addRecordingToPlaylist(playlist.short_id, props.sessionRecordingId)
                return [playlist, ...values.currentPlaylists]
            },

            removeFromPlaylist: async ({ playlist }) => {
                await api.recordings.removeRecordingFromPlaylist(playlist.short_id, props.sessionRecordingId)
                return values.currentPlaylists.filter((x) => x.short_id !== playlist.short_id)
            },
        },
    })),
    reducers(() => ({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query, submitNewPlaylistSuccess: () => '' }],
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
        modifiyingPlaylist: [
            null as SessionRecordingPlaylistType | null,
            {
                addToPlaylist: (_, { playlist }) => playlist,
                removeFromPlaylist: (_, { playlist }) => playlist,
                setShowPlaylistPopup: () => null,
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
                actions.loadPlaylistsForRecording()
                actions.setPause()
            }
        },
        addToPlaylistSuccess: ({ payload }) => {
            if (payload?.playlist.short_id) {
                sessionRecordingsListLogic
                    .findMounted({ playlistShortId: payload?.playlist.short_id })
                    ?.actions.loadPinnedRecordings({})
            }
        },
        removeFromPlaylistSuccess: ({ payload }) => {
            if (payload?.playlist.short_id) {
                sessionRecordingsListLogic
                    .findMounted({ playlistShortId: payload?.playlist.short_id })
                    ?.actions.loadPinnedRecordings({})
            }
        },
    })),
    selectors(() => ({
        allPlaylists: [
            (s) => [s.playlists, s.currentPlaylists, s.searchQuery],
            (playlists, currentPlaylists, searchQuery) => {
                const otherPlaylists = searchQuery
                    ? playlists
                    : playlists.filter((x) => !currentPlaylists.find((y) => x.short_id === y.short_id))

                const selectedPlaylists = !searchQuery ? currentPlaylists : []

                const results: {
                    selected: boolean
                    playlist: SessionRecordingPlaylistType
                }[] = [
                    ...selectedPlaylists.map((x) => ({
                        selected: true,
                        playlist: x,
                    })),
                    ...otherPlaylists.map((x) => ({
                        selected: !!currentPlaylists.find((y) => x.short_id === y.short_id),
                        playlist: x,
                    })),
                ]

                return results
            },
        ],
    })),
])
