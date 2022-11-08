import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { Breadcrumb, RecordingFilters, SessionRecordingPlaylistType, SessionRecordingsTabs } from '~/types'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'
import { urls } from 'scenes/urls'
import equal from 'fast-deep-equal'
import { lemonToast } from '@posthog/lemon-ui'
import { beforeUnload } from 'kea-router'

export interface SessionRecordingsPlaylistLogicProps {
    shortId: string
}

export const sessionRecordingsPlaylistLogic = kea<sessionRecordingsPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsPlaylistLogic', key]),
    props({} as SessionRecordingsPlaylistLogicProps),
    key((props) => props.shortId),
    actions({
        loadPlaylist: true,
        setFilters: (filters: RecordingFilters | null) => ({ filters }),
        saveChanges: true,
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
                    await breakpoint(100)
                    const response = api.recordings.updatePlaylist(props.shortId, playlist)
                    breakpoint()

                    lemonToast.success('Playlist updated successfully')

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
                    name: 'Recording Playlists',
                    path: urls.sessionRecordings(SessionRecordingsTabs.Playlists),
                },
                {
                    name: playlist?.name || 'Untitled Playlist',
                    path: urls.sessionRecordingPlaylist(playlist?.short_id || ''),
                },
            ],
        ],
        hasChanges: [
            (s) => [s.playlist, s.filters],
            (playlist, filters): boolean => !equal(playlist?.filters, filters),
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadPlaylist()
    }),
])
