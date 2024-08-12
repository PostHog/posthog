import { lemonToast } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import api from 'lib/api'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import {
    deletePlaylist,
    duplicatePlaylist,
    getPlaylist,
    summarizePlaylistFilters,
    updatePlaylist,
} from 'scenes/session-recordings/playlist/playlistUtils'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import {
    Breadcrumb,
    LegacyRecordingFilters,
    RecordingUniversalFilters,
    ReplayTabs,
    SessionRecordingPlaylistType,
    SessionRecordingType,
} from '~/types'

import { addRecordingToPlaylist, removeRecordingFromPlaylist } from '../player/utils/playerUtils'
import { filtersFromUniversalFilterGroups, isUniversalFilters } from '../utils'
import { convertLegacyFiltersToUniversalFilters, PINNED_RECORDINGS_LIMIT } from './sessionRecordingsPlaylistLogic'
import type { sessionRecordingsPlaylistSceneLogicType } from './sessionRecordingsPlaylistSceneLogicType'

export interface SessionRecordingsPlaylistLogicProps {
    shortId: string
}

export const sessionRecordingsPlaylistSceneLogic = kea<sessionRecordingsPlaylistSceneLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsPlaylistSceneLogic', key]),
    props({} as SessionRecordingsPlaylistLogicProps),
    key((props) => props.shortId),
    connect({
        values: [cohortsModel, ['cohortsById'], sceneLogic, ['activeScene']],
    }),
    actions({
        updatePlaylist: (properties?: Partial<SessionRecordingPlaylistType>, silent = false) => ({
            properties,
            silent,
        }),
        setFilters: (filters: LegacyRecordingFilters | RecordingUniversalFilters | null) => ({ filters }),
        loadPinnedRecordings: true,
        onPinnedChange: (recording: SessionRecordingType, pinned: boolean) => ({ pinned, recording }),
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
                            router.actions.replace(urls.replay(ReplayTabs.Playlists))
                        })
                    }
                    return null
                },
            },
        ],

        pinnedRecordings: [
            null as SessionRecordingType[] | null,
            {
                loadPinnedRecordings: async (_, breakpoint) => {
                    if (!props.shortId) {
                        return null
                    }

                    await breakpoint(100)
                    const response = await api.recordings.listPlaylistRecordings(props.shortId, {
                        limit: PINNED_RECORDINGS_LIMIT,
                    })
                    breakpoint()
                    return response.results
                },

                onPinnedChange: async ({ recording, pinned }) => {
                    let newResults = values.pinnedRecordings ?? []

                    newResults = newResults.filter((r) => r.id !== recording.id)

                    if (pinned) {
                        await addRecordingToPlaylist(props.shortId, recording.id)
                        newResults.push(recording)
                    } else {
                        await removeRecordingFromPlaylist(props.shortId, recording.id)
                    }

                    return newResults
                },
            },
        ],
    })),
    reducers(() => ({
        filters: [
            null as LegacyRecordingFilters | RecordingUniversalFilters | null,
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
        enabled: (newLocation) =>
            values.activeScene === Scene.ReplayPlaylist &&
            values.hasChanges &&
            newLocation?.pathname !== router.values.location.pathname,
        message: 'Leave playlist?\nChanges you made will be discarded.',
        onConfirm: () => {
            actions.setFilters(values.playlist?.filters || null)
        },
    })),

    selectors(({ asyncActions }) => ({
        breadcrumbs: [
            (s) => [s.playlist],
            (playlist): Breadcrumb[] => [
                {
                    key: Scene.Replay,
                    name: 'Replay',
                    path: urls.replay(),
                },
                {
                    key: ReplayTabs.Playlists,
                    name: 'Playlists',
                    path: urls.replay(ReplayTabs.Playlists),
                },
                {
                    key: [Scene.ReplayPlaylist, playlist?.short_id || 'new'],
                    name: playlist?.name || playlist?.derived_name || 'Unnamed',
                    onRename: async (name: string) => {
                        if (!playlist) {
                            lemonToast.error('Cannot rename unsaved playlist')
                            return
                        }
                        await asyncActions.updatePlaylist({ short_id: playlist.short_id, name })
                    },
                },
            ],
        ],
        hasChanges: [
            (s) => [s.playlist, s.filters],
            (playlist, filters): boolean => {
                return !equal(playlist?.filters, filters)
            },
        ],
        derivedName: [
            (s) => [s.filters, s.cohortsById],
            (filters, cohortsById) => {
                if (!filters) {
                    return 'Unnamed'
                }

                const universalFilters = isUniversalFilters(filters)
                    ? filters
                    : convertLegacyFiltersToUniversalFilters({}, filters)

                return (
                    summarizePlaylistFilters(filtersFromUniversalFilterGroups(universalFilters), cohortsById)?.slice(
                        0,
                        400
                    ) || 'Unnamed'
                )
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.getPlaylist()
        actions.loadPinnedRecordings()
    }),
])
