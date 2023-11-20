import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { objectClean, objectsEqual, toParams } from 'lib/utils'
import { SessionRecordingPlaylistType, ReplayTabs } from '~/types'
import { dayjs } from 'lib/dayjs'
import type { savedSessionRecordingPlaylistsLogicType } from './savedSessionRecordingPlaylistsLogicType'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { createPlaylist, deletePlaylist } from '../playlist/playlistUtils'
import { lemonToast } from '@posthog/lemon-ui'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export const PLAYLISTS_PER_PAGE = 30

export interface SavedSessionRecordingPlaylistsResult extends PaginatedResponse<SessionRecordingPlaylistType> {
    count: number
    /** not in the API response */
    filters?: SavedSessionRecordingPlaylistsFilters | null
}

export interface SavedSessionRecordingPlaylistsFilters {
    order: string
    search: string
    createdBy: number | 'All users'
    dateFrom: string | dayjs.Dayjs | undefined | null
    dateTo: string | dayjs.Dayjs | undefined | null
    page: number
    pinned: boolean
}

export interface SavedSessionRecordingPlaylistsLogicProps {
    tab: ReplayTabs
}

export const DEFAULT_PLAYLIST_FILTERS = {
    createdBy: 'All users',
    page: 1,
    dateFrom: 'all',
}

export const savedSessionRecordingPlaylistsLogic = kea<savedSessionRecordingPlaylistsLogicType>([
    path((key) => ['scenes', 'session-recordings', 'saved-playlists', 'savedSessionRecordingPlaylistsLogic', key]),
    props({} as SavedSessionRecordingPlaylistsLogicProps),
    key((props) => props.tab),
    connect({
        actions: [eventUsageLogic, ['reportRecordingPlaylistCreated']],
    }),

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
                setSavedPlaylistsFilters: (state, { filters }) =>
                    objectClean({
                        ...(state || {}),
                        ...filters,
                        // Reset page on filter change EXCEPT if it's page that's being updated
                        ...('page' in filters ? {} : { page: 1 }),
                    }),
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
                values.playlists.results = values.playlists.results.filter((x) => x.short_id !== playlist.short_id)
                return values.playlists
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

                values.playlists.results = [newPlaylist, ...values.playlists.results]

                return values.playlists
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
                    // Sync with `cleanFilters` function
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
                  }
              ]
            | void => {
            if (router.values.location.pathname === urls.replay(ReplayTabs.Playlists)) {
                const nextValues = values.filters
                const urlValues = objectClean(router.values.searchParams)
                if (!objectsEqual(nextValues, urlValues)) {
                    return [urls.replay(ReplayTabs.Playlists), nextValues, {}, { replace: false }]
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
