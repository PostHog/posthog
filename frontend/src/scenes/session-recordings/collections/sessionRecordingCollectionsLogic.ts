import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { objectClean, objectsEqual, toParams } from 'lib/utils'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'
import { urls } from 'scenes/urls'

import {
    ReplayTabs,
    SavedSessionRecordingPlaylistsFilters,
    SavedSessionRecordingPlaylistsResult,
    SessionRecordingPlaylistType,
} from '~/types'

import { createPlaylist, deletePlaylist } from '../playlist/playlistUtils'
import type { sessionRecordingCollectionsLogicType } from './sessionRecordingCollectionsLogicType'

export const PLAYLISTS_PER_PAGE = 30

export const DEFAULT_PLAYLIST_FILTERS = {
    createdBy: 'All users',
    page: 1,
    dateFrom: 'all',
}

export const sessionRecordingCollectionsLogic = kea<sessionRecordingCollectionsLogicType>([
    path(() => ['scenes', 'session-recordings', 'collections', 'sessionRecordingCollectionsLogic']),
    connect(() => ({
        actions: [sessionRecordingEventUsageLogic, ['reportRecordingPlaylistCreated']],
    })),

    actions(() => ({
        setSavedPlaylistsFilters: (filters: Partial<SavedSessionRecordingPlaylistsFilters>) => ({
            filters,
        }),
        loadPlaylists: true,
        updatePlaylist: (
            shortId: SessionRecordingPlaylistType['short_id'],
            properties: Partial<SessionRecordingPlaylistType>
        ) => ({ shortId, properties }),
        deletePlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
        duplicatePlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
    })),
    reducers(() => ({
        filters: [
            DEFAULT_PLAYLIST_FILTERS as SavedSessionRecordingPlaylistsFilters | Record<string, any>,
            {
                setSavedPlaylistsFilters: (state, { filters }) => {
                    const merged = {
                        ...state,
                        ...filters,
                        ...('page' in filters ? {} : { page: 1 }),
                    }

                    const cleaned = Object.fromEntries(
                        Object.entries(merged).filter(
                            ([key, value]) =>
                                key === 'page' ||
                                DEFAULT_PLAYLIST_FILTERS[key as keyof typeof DEFAULT_PLAYLIST_FILTERS] !== value
                        )
                    )

                    return objectClean(cleaned)
                },
            },
        ],
        loadPlaylistsFailed: [
            false,
            {
                loadPlaylists: () => false,
                loadPlaylistsSuccess: () => false,
                loadPlaylistsFailure: () => true,
            },
        ],
    })),
    loaders(({ values, actions }) => ({
        playlists: {
            __default: { results: [], count: 0, filters: null } as SavedSessionRecordingPlaylistsResult,
            loadPlaylists: async (_, breakpoint) => {
                if (values.playlists.filters !== null) {
                    await breakpoint(300)
                }

                const filters = { ...values.filters }
                const createdBy = filters.createdBy === 'All users' ? undefined : filters.createdBy

                const params = {
                    limit: PLAYLISTS_PER_PAGE,
                    offset: Math.max(0, (filters.page - 1) * PLAYLISTS_PER_PAGE),
                    order: filters.order ?? '-last_modified_at', // Sync with `sorting` selector
                    created_by: createdBy ?? undefined,
                    search: filters.search || undefined,
                    date_from: filters.dateFrom && filters.dateFrom != 'all' ? filters.dateFrom : undefined,
                    date_to: filters.dateTo ?? undefined,
                    pinned: filters.pinned ? true : undefined,
                    type: 'collection',
                }

                const response = await api.recordings.listPlaylists(toParams(params))
                breakpoint()

                return response
            },
            updatePlaylist: async ({ shortId, properties }, breakpoint) => {
                await breakpoint(100)
                const updatedPlaylist = await api.recordings.updatePlaylist(shortId, properties)
                breakpoint()

                const index = values.playlists.results.findIndex((x) => x.short_id === updatedPlaylist.short_id)
                if (index > -1) {
                    values.playlists.results[index] = updatedPlaylist
                }

                return { ...values.playlists, results: [...values.playlists.results] }
            },
            deletePlaylist: async ({ playlist }) => {
                await deletePlaylist(playlist, () => actions.loadPlaylists())
                return {
                    ...values.playlists,
                    results: values.playlists.results.filter((x) => x.short_id !== playlist.short_id),
                }
            },

            duplicatePlaylist: async ({ playlist }, breakpoint) => {
                await breakpoint(100)

                const { id, short_id, ...partialPlaylist } = playlist
                partialPlaylist.name = partialPlaylist.name ? partialPlaylist.name + ' (copy)' : ''

                const newPlaylist = await createPlaylist(partialPlaylist)
                actions.reportRecordingPlaylistCreated('duplicate')

                breakpoint()
                if (!newPlaylist) {
                    return values.playlists
                }

                lemonToast.success('Playlist duplicated successfully')

                return { ...values.playlists, results: [newPlaylist, ...values.playlists.results] }
            },
        },
    })),
    listeners(({ actions }) => ({
        setSavedPlaylistsFilters: () => {
            actions.loadPlaylists()
        },
    })),

    selectors(({ actions }) => ({
        sorting: [
            (s) => [s.filters],
            (filters): Sorting | null => {
                if (!filters.order) {
                    return {
                        columnKey: 'last_modified_at',
                        order: -1,
                    }
                }
                return filters.order.startsWith('-')
                    ? {
                          columnKey: filters.order.slice(1),
                          order: -1,
                      }
                    : {
                          columnKey: filters.order,
                          order: 1,
                      }
            },
        ],
        pagination: [
            (s) => [s.filters, s.playlists],
            (filters, playlists): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: PLAYLISTS_PER_PAGE,
                    currentPage: filters.page,
                    entryCount: playlists.count,
                    onBackward: playlists.previous
                        ? () =>
                              actions.setSavedPlaylistsFilters({
                                  page: filters.page - 1,
                              })
                        : undefined,
                    onForward: playlists.next
                        ? () =>
                              actions.setSavedPlaylistsFilters({
                                  page: filters.page + 1,
                              })
                        : undefined,
                }
            },
        ],
    })),
    actionToUrl(({ values }) => {
        const changeUrl = ():
            | [
                  string,
                  Record<string, any>,
                  Record<string, any>,
                  {
                      replace: boolean
                  },
              ]
            | void => {
            if (removeProjectIdIfPresent(router.values.location.pathname) === urls.replay(ReplayTabs.Playlists)) {
                const nextValues = values.filters
                const urlValues = objectClean(router.values.searchParams)

                // Only include non-default values in URL
                // We always include the page number in the URL
                const nonDefaultValues = objectClean(
                    Object.fromEntries(
                        Object.entries(nextValues).filter(
                            ([key, value]) =>
                                key === 'page' ||
                                DEFAULT_PLAYLIST_FILTERS[key as keyof typeof DEFAULT_PLAYLIST_FILTERS] !== value
                        )
                    )
                )

                if (!objectsEqual(nonDefaultValues, urlValues)) {
                    return [urls.replay(ReplayTabs.Playlists), nonDefaultValues, {}, { replace: false }]
                }
            }
        }
        return {
            loadPlaylists: changeUrl,
            setSavedPlaylistsFilters: changeUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.replay(ReplayTabs.Playlists)]: (_, searchParams) => {
            const currentFilters = values.filters
            const nextFilters = objectClean(searchParams)
            if (!objectsEqual(currentFilters, nextFilters)) {
                actions.setSavedPlaylistsFilters(nextFilters)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPlaylists()
    }),
])
