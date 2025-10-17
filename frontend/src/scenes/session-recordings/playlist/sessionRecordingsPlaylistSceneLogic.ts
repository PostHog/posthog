import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import {
    createPlaylist,
    deletePlaylist,
    duplicatePlaylist,
    getPlaylist,
    summarizePlaylistFilters,
    updatePlaylist,
} from 'scenes/session-recordings/playlist/playlistUtils'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'
import { urls } from 'scenes/urls'

import { getLastNewFolder } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { cohortsModel } from '~/models/cohortsModel'
import {
    Breadcrumb,
    LegacyRecordingFilters,
    ProjectTreeRef,
    RecordingUniversalFilters,
    ReplayTabs,
    SessionRecordingPlaylistType,
    SessionRecordingType,
} from '~/types'

import { addRecordingToPlaylist, removeRecordingFromPlaylist } from '../player/utils/playerUtils'
import { filtersFromUniversalFilterGroups, isUniversalFilters } from '../utils'
import { PINNED_RECORDINGS_LIMIT, convertLegacyFiltersToUniversalFilters } from './sessionRecordingsPlaylistLogic'
import type { sessionRecordingsPlaylistSceneLogicType } from './sessionRecordingsPlaylistSceneLogicType'

export interface SessionRecordingsPlaylistLogicProps {
    shortId: string
}

export const sessionRecordingsPlaylistSceneLogic = kea<sessionRecordingsPlaylistSceneLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsPlaylistSceneLogic', key]),
    props({} as SessionRecordingsPlaylistLogicProps),
    key((props) => props.shortId),
    connect(() => ({
        values: [cohortsModel, ['cohortsById'], sceneLogic, ['activeSceneId'], featureFlagLogic, ['featureFlags']],
        actions: [sessionRecordingEventUsageLogic, ['reportRecordingPlaylistCreated']],
    })),
    actions({
        updatePlaylist: (properties?: Partial<SessionRecordingPlaylistType>, silent = false) => ({
            properties,
            silent,
        }),
        setFilters: (filters: LegacyRecordingFilters | RecordingUniversalFilters | null) => ({ filters }),
        loadPinnedRecordings: true,
        onPinnedChange: (recording: SessionRecordingType, pinned: boolean) => ({ pinned, recording }),
        markPlaylistViewed: true,
    }),
    loaders(({ actions, values, props }) => ({
        playlist: [
            null as SessionRecordingPlaylistType | null,
            {
                getPlaylist: async () => {
                    if (props.shortId === 'new') {
                        const folder = getLastNewFolder() ?? 'Unfiled/Replay playlists'
                        const playlist = await createPlaylist({ _create_in_folder: folder }, true)
                        actions.reportRecordingPlaylistCreated('new')
                        return playlist
                    }

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
                    if (!props.shortId || props.shortId === 'new') {
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
        getPlaylistSuccess: ({ playlist }) => {
            if (values.playlist?.derived_name !== values.derivedName) {
                // This keeps the derived name up to date if the playlist changes
                actions.updatePlaylist({ derived_name: values.derivedName }, true)
            }

            if (playlist?.filters) {
                actions.markPlaylistViewed()
            }
        },
        markPlaylistViewed: async () => {
            if (!values.playlist) {
                return
            }
            await api.recordings.playlistViewed(values.playlist.short_id)
        },
    })),

    beforeUnload(({ values, actions }) => ({
        enabled: (newLocation) => {
            const response =
                values.activeSceneId === Scene.ReplayPlaylist &&
                values.hasChanges &&
                removeProjectIdIfPresent(newLocation?.pathname ?? '') !==
                    removeProjectIdIfPresent(router.values.location.pathname) &&
                !newLocation?.pathname.includes('/replay/playlists/new') &&
                !router.values.location.pathname.includes('/replay/playlists/new')
            return response
        },
        message: 'Leave playlist?\nChanges you made will be discarded.',
        onConfirm: () => {
            actions.setFilters(values.playlist?.filters || null)
        },
    })),

    selectors(() => ({
        breadcrumbs: [
            (s) => [s.playlist, s.featureFlags],
            (playlist): Breadcrumb[] => [
                {
                    key: ReplayTabs.Playlists,
                    name: 'Collections',
                    path: urls.replay(ReplayTabs.Playlists),
                    iconType: 'session_replay',
                },
                {
                    key: [Scene.ReplayPlaylist, playlist?.short_id || 'new'],
                    name: playlist?.name || playlist?.derived_name || 'Unnamed',
                    iconType: 'session_replay',
                },
            ],
        ],
        projectTreeRef: [
            () => [(_, props: SessionRecordingsPlaylistLogicProps) => props.shortId],
            (shortId): ProjectTreeRef => ({ type: 'session_recording_playlist', ref: String(shortId) }),
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

    afterMount(({ actions, props }) => {
        if (props.shortId && props.shortId !== 'new') {
            actions.getPlaylist()
            actions.loadPinnedRecordings()
        }
    }),

    urlToAction(({ actions }) => ({
        '/replay/playlists/new': () => actions.getPlaylist(),
    })),
])
