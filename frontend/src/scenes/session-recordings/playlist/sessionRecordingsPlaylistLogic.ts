import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { Breadcrumb, RecordingFilters, SessionRecordingPlaylistType, SessionRecordingsTabs } from '~/types'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'
import { urls } from 'scenes/urls'
import equal from 'fast-deep-equal'
import { lemonToast } from '@posthog/lemon-ui'
import { beforeUnload } from 'kea-router'
import { cohortsModel } from '~/models/cohortsModel'
import { duplicatePlaylist, summarizePlaylistFilters } from 'scenes/session-recordings/playlist/playlistUtils'

export interface SessionRecordingsPlaylistLogicProps {
    shortId: string
}

export const sessionRecordingsPlaylistLogic = kea<sessionRecordingsPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsPlaylistLogic', key]),
    props({} as SessionRecordingsPlaylistLogicProps),
    key((props) => props.shortId),
    connect({
        values: [cohortsModel, ['cohortsById']],
    }),
    actions({
        loadPlaylist: true,
        setFilters: (filters: RecordingFilters | null) => ({ filters }),
        saveChanges: true,
        duplicatePlaylist: true,
    }),
    loaders(({ props, values }) => ({
        playlist: [
            null as SessionRecordingPlaylistType | null,
            {
                loadPlaylist: async () => {
                    return api.recordings.getPlaylist(props.shortId)
                },

                updatePlaylist: async (playlist: Partial<SessionRecordingPlaylistType>, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.recordings.updatePlaylist(props.shortId, {
                        ...playlist,
                        derived_name: values.derivedName, // Makes sure derived name is kept up to date
                    })
                    breakpoint()

                    lemonToast.success('Playlist updated successfully')

                    return response
                },

                updatePlaylistSilently: async (playlist: Partial<SessionRecordingPlaylistType>, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.recordings.updatePlaylist(props.shortId, {
                        ...playlist,
                        derived_name: values.derivedName, // Makes sure derived name is kept up to date
                    })
                    breakpoint()

                    return response
                },

                duplicatePlaylist: async (_, breakpoint) => {
                    await breakpoint(100)
                    if (!values.playlist) {
                        return null
                    }
                    const response = await duplicatePlaylist(values.playlist)

                    return response
                },
            },
        ],
    })),

    reducers(({}) => ({
        filters: [
            null as RecordingFilters | null,
            {
                loadPlaylistSuccess: (_, { playlist }) => playlist.filters || null,
                setFilters: (_, { filters }) => filters,
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        saveChanges: async () => {
            actions.updatePlaylist({ filters: values.filters || undefined })
        },
        loadPlaylistSuccess: async () => {
            if (values.playlist?.derived_name !== values.derivedName) {
                // This keeps the derived name up to date if the playlist changes
                actions.updatePlaylistSilently({ derived_name: values.derivedName })
            }
        },
    })),

    beforeUnload(({ values, actions }) => ({
        enabled: () => values.hasChanges,
        message: 'Leave playlist? Changes you made will be discarded.',
        onConfirm: () => {
            actions.setFilters(values.playlist?.filters || null)
        },
    })),

    selectors(({}) => ({
        breadcrumbs: [
            (s) => [s.playlist],
            (playlist): Breadcrumb[] => [
                {
                    name: 'Saved Playlists',
                    path: urls.sessionRecordings(SessionRecordingsTabs.Playlists),
                },
                {
                    name: playlist?.name || playlist?.derived_name || '(Untitled)',
                    path: urls.sessionRecordingPlaylist(playlist?.short_id || ''),
                },
            ],
        ],
        hasChanges: [
            (s) => [s.playlist, s.filters],
            (playlist, filters): boolean => !equal(playlist?.filters, filters),
        ],
        derivedName: [
            (s) => [s.filters, s.cohortsById],
            (filters, cohortsById) =>
                summarizePlaylistFilters(filters || {}, cohortsById)?.slice(0, 400) || '(Untitled)',
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadPlaylist()
    }),
])
