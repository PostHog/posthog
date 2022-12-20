import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { Breadcrumb, RecordingFilters, SessionRecordingPlaylistType, SessionRecordingsTabs } from '~/types'
import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'
import { urls } from 'scenes/urls'
import equal from 'fast-deep-equal'
import { beforeUnload, router } from 'kea-router'
import { cohortsModel } from '~/models/cohortsModel'
import {
    deletePlaylist,
    duplicatePlaylist,
    getPlaylist,
    summarizePlaylistFilters,
    updatePlaylist,
} from 'scenes/session-recordings/playlist/playlistUtils'
import { loaders } from 'kea-loaders'

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
        updatePlaylist: (properties?: Partial<SessionRecordingPlaylistType>, silent = false) => ({
            properties,
            silent,
        }),
        setFilters: (filters: RecordingFilters | null) => ({ filters }),
    }),
    loaders(({ values, props }) => ({
        playlist: [
            null as SessionRecordingPlaylistType | null,
            {
                getPlaylist: async () => {
                    return getPlaylist(props.shortId)
                },
                updatePlaylist: async ({ properties, silent }) => {
                    if (!values.playlist?.short_id) {
                        return values.playlist
                    }
                    return updatePlaylist(
                        values.playlist?.short_id,
                        properties ?? { filters: values.filters || undefined },
                        silent
                    )
                },
                duplicatePlaylist: async () => {
                    return duplicatePlaylist(values.playlist ?? {}, true)
                },
                deletePlaylist: async () => {
                    if (values.playlist) {
                        return deletePlaylist(values.playlist, () => {
                            router.actions.replace(urls.sessionRecordings(SessionRecordingsTabs.Playlists))
                        })
                    }
                    return null
                },
            },
        ],
    })),
    reducers(({}) => ({
        filters: [
            null as RecordingFilters | null,
            {
                getPlaylistSuccess: (_, { playlist }) => playlist?.filters || null,
                updatePlaylistSuccess: (_, { playlist }) => playlist?.filters || null,
                setFilters: (_, { filters }) => filters,
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        getPlaylistSuccess: () => {
            if (values.playlist?.derived_name !== values.derivedName) {
                // This keeps the derived name up to date if the playlist changes
                actions.updatePlaylist({ derived_name: values.derivedName }, true)
            }
        },
    })),

    beforeUnload(({ values, actions }) => ({
        enabled: (newLocation) => values.hasChanges && newLocation?.pathname !== router.values.location.pathname,
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
                    name: 'Recordings',
                    path: urls.sessionRecordings(),
                },
                {
                    name: 'Playlists',
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
            (playlist, filters): boolean => {
                console.log(playlist?.filters, filters)
                return !equal(playlist?.filters, filters)
            },
        ],
        derivedName: [
            (s) => [s.filters, s.cohortsById],
            (filters, cohortsById) =>
                summarizePlaylistFilters(filters || {}, cohortsById)?.slice(0, 400) || '(Untitled)',
        ],
    })),

    afterMount(({ actions }) => {
        actions.getPlaylist()
    }),
])
