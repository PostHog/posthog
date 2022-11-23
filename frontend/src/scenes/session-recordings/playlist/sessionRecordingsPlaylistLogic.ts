import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { Breadcrumb, RecordingFilters, SessionRecordingPlaylistType, SessionRecordingsTabs } from '~/types'
import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'
import { urls } from 'scenes/urls'
import equal from 'fast-deep-equal'
import { beforeUnload } from 'kea-router'
import { cohortsModel } from '~/models/cohortsModel'
import { summarizePlaylistFilters } from 'scenes/session-recordings/playlist/playlistUtils'
import { savedSessionRecordingPlaylistModelLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'

export interface SessionRecordingsPlaylistLogicProps {
    shortId: string
}

export const sessionRecordingsPlaylistLogic = kea<sessionRecordingsPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsPlaylistLogic', key]),
    props({} as SessionRecordingsPlaylistLogicProps),
    key((props) => props.shortId),
    connect({
        values: [
            cohortsModel,
            ['cohortsById'],
            savedSessionRecordingPlaylistModelLogic,
            ['_playlistModel', '_playlistModelLoading'],
        ],
        actions: [
            savedSessionRecordingPlaylistModelLogic,
            [
                'loadSavedPlaylist',
                'loadSavedPlaylistSuccess',
                'updateSavedPlaylist',
                'updateSavedPlaylistSuccess',
                'duplicateSavedPlaylist',
                'duplicateSavedPlaylistSuccess',
                'deleteSavedPlaylistWithUndo',
            ],
        ],
    }),
    actions({
        getPlaylist: true,
        setPlaylist: (playlist: SessionRecordingPlaylistType | null) => ({ playlist }),
        setFilters: (filters: RecordingFilters | null) => ({ filters }),
        saveChanges: true,
    }),
    reducers(({}) => ({
        playlist: [
            null as SessionRecordingPlaylistType | null,
            {
                setPlaylist: (oldPlaylist, { playlist }) => playlist || oldPlaylist,
            },
        ],
        filters: [
            null as RecordingFilters | null,
            {
                setPlaylist: (_, { playlist }) => playlist?.filters || null,
                setFilters: (_, { filters }) => filters,
            },
        ],
    })),

    listeners(({ actions, values, props }) => ({
        getPlaylist: () => {
            actions.loadSavedPlaylist(props.shortId)
        },
        saveChanges: () => {
            actions.updateSavedPlaylist({ short_id: props.shortId, filters: values.filters || undefined })
        },
        updateSavedPlaylistSuccess: () => {
            actions.setPlaylist(values._playlistModel)
        },
        duplicateSavedPlaylistSuccess: () => {
            actions.setPlaylist(values._playlistModel)
        },
        loadSavedPlaylistSuccess: () => {
            actions.setPlaylist(values._playlistModel)

            if (values.playlist?.derived_name !== values.derivedName) {
                // This keeps the derived name up to date if the playlist changes
                actions.updateSavedPlaylist({ short_id: props.shortId, derived_name: values.derivedName }, true)
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
        playlistLoading: [(s) => [s._playlistModelLoading], (_playlistModelLoading) => !!_playlistModelLoading],
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
        actions.getPlaylist()
    }),
])
