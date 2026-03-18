import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { lazyLoaders, loaders } from 'kea-loaders'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import {
    SessionRecordingPlayerLogicProps,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { addRecordingToPlaylist, removeRecordingFromPlaylist } from 'scenes/session-recordings/player/utils/playerUtils'
import { createPlaylist } from 'scenes/session-recordings/playlist/playlistUtils'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import { SessionRecordingPlaylistType } from '~/types'

import type { playlistPopoverLogicType } from './playlistPopoverLogicType'

export const playlistPopoverLogic = kea<playlistPopoverLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playlist-popover', 'playlistPopoverLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        actions: [
            sessionRecordingPlayerLogic(props),
            ['setPause'],
            sessionRecordingEventUsageLogic,
            ['reportRecordingPinnedToList', 'reportRecordingPlaylistCreated'],
        ],
    })),
    actions(() => ({
        setSearchQuery: (query: string) => ({ query }),
        loadPlaylists: true,
        loadPlaylistsForRecording: true,
        addToPlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
        removeFromPlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
        setNewFormShowing: (show: boolean) => ({ show }),
        setShowPlaylistPopover: (show: boolean) => ({ show }),
    })),
    lazyLoaders(({ values }) => ({
        playlists: {
            __default: [] as SessionRecordingPlaylistType[],
            loadPlaylists: async (_, breakpoint) => {
                await breakpoint(300)
                const response = await api.recordings.listPlaylists(
                    toParams({ search: values.searchQuery, type: 'collection' })
                )
                breakpoint()
                return response.results
            },
        },
    })),
    loaders(({ values, props, actions }) => ({
        currentPlaylists: {
            __default: [] as SessionRecordingPlaylistType[],
            loadPlaylistsForRecording: async (_, breakpoint) => {
                await breakpoint(300)
                const response = await api.recordings.listPlaylists(
                    toParams({ session_recording_id: props.sessionRecordingId, type: 'collection' })
                )
                breakpoint()
                return response.results
            },

            addToPlaylist: async ({ playlist }) => {
                await addRecordingToPlaylist(playlist.short_id, props.sessionRecordingId, true)
                actions.reportRecordingPinnedToList(true)
                return [playlist, ...values.currentPlaylists]
            },

            removeFromPlaylist: async ({ playlist }) => {
                await removeRecordingFromPlaylist(playlist.short_id, props.sessionRecordingId, true)
                actions.reportRecordingPinnedToList(false)
                return values.currentPlaylists.filter((x) => x.short_id !== playlist.short_id)
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
        showPlaylistPopover: [
            false,
            {
                setShowPlaylistPopover: (_, { show }) => show,
            },
        ],
        modifyingPlaylist: [
            null as SessionRecordingPlaylistType | null,
            {
                addToPlaylist: (_, { playlist }) => playlist,
                removeFromPlaylist: (_, { playlist }) => playlist,
                setShowPlaylistPopover: () => null,
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
                    type: 'collection',
                })

                actions.reportRecordingPlaylistCreated('pin')

                if (!newPlaylist) {
                    // This indicates the billing popover has been shown, so we should close the modal
                    actions.setShowPlaylistPopover(false)
                    return
                }

                // TODO change to currentPlaylists isn't recalculating the selector
                actions.addToPlaylist(newPlaylist)
                actions.setNewFormShowing(false)
                actions.resetNewPlaylist()
                actions.setSearchQuery('')
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

        setShowPlaylistPopover: ({ show }) => {
            if (show) {
                actions.loadPlaylists()
                actions.loadPlaylistsForRecording()
                actions.setPause()
            }
        },
    })),
    selectors(() => ({
        allPlaylists: [
            (s) => [s.playlists, s.currentPlaylists, s.searchQuery],
            (playlists, currentPlaylists, searchQuery) => {
                const nonSyntheticPlaylists = playlists.filter((x) => !x.is_synthetic)
                const nonSyntheticCurrentPlaylists = currentPlaylists.filter((x) => !x.is_synthetic)

                const otherPlaylists = searchQuery
                    ? nonSyntheticPlaylists
                    : nonSyntheticPlaylists.filter(
                          (x) => !nonSyntheticCurrentPlaylists.find((y) => x.short_id === y.short_id)
                      )

                const selectedPlaylists = !searchQuery ? nonSyntheticCurrentPlaylists : []

                const results: {
                    selected: boolean
                    playlist: SessionRecordingPlaylistType
                }[] = [
                    ...selectedPlaylists.map((x) => ({
                        selected: true,
                        playlist: x,
                    })),
                    ...otherPlaylists.map((x) => ({
                        selected: !!nonSyntheticCurrentPlaylists.find((y) => x.short_id === y.short_id),
                        playlist: x,
                    })),
                ]

                return results
            },
        ],
        pinnedCount: [
            (s) => [s.currentPlaylists],
            (currentPlaylists) => currentPlaylists.filter((x) => !x.is_synthetic).length,
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadPlaylistsForRecording()
    }),
])
