import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { objectClean, objectsEqual, toParams } from 'lib/utils'
import { SessionRecordingPlaylistType, SessionRecordingsTabs } from '~/types'
import { dayjs } from 'lib/dayjs'
import type { savedSessionRecordingPlaylistsLogicType } from './savedSessionRecordingPlaylistsLogicType'
import { Sorting } from 'lib/components/LemonTable'
import { PaginationManual } from 'lib/components/PaginationControl'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { savedSessionRecordingPlaylistModelLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'

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
    dateFrom: string | dayjs.Dayjs | undefined | 'all' | null
    dateTo: string | dayjs.Dayjs | undefined | null
    page: number
    pinned: boolean
}

export interface SavedSessionRecordingPlaylistsLogicProps {
    tab: SessionRecordingsTabs
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
        actions: [
            savedSessionRecordingPlaylistModelLogic,
            [
                'createSavedPlaylist',
                'duplicateSavedPlaylist',
                'updateSavedPlaylist',
                'updateSavedPlaylistSuccess',
                'deleteSavedPlaylistWithUndo',
                'deleteSavedPlaylistWithUndoSuccess',
            ],
        ],
        values: [savedSessionRecordingPlaylistModelLogic, ['_savedPlaylistLoading', '_savedPlaylist']],
    }),
    actions(() => ({
        setSavedPlaylistsFilters: (filters: Partial<SavedSessionRecordingPlaylistsFilters>) => ({
            filters,
        }),
        loadPlaylists: true,
        updateLocalPlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
        deleteLocalPlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
    })),
    reducers(({}) => ({
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
            updateLocalPlaylist: async ({ playlist }) => {
                const index = values.playlists.results.findIndex((x) => x.short_id === playlist.short_id)
                if (index > -1) {
                    values.playlists.results[index] = playlist
                }
                return values.playlists
            },
            deleteLocalPlaylist: async ({ playlist }) => {
                values.playlists.results = values.playlists.results.filter((x) => x.short_id !== playlist.short_id)
                actions.loadPlaylists()
                return values.playlists
            },
        },
    })),
    listeners(({ actions, values }) => ({
        setSavedPlaylistsFilters: () => {
            actions.loadPlaylists()
        },
        updateSavedPlaylistSuccess: () => {
            actions.updateLocalPlaylist(values._savedPlaylist)
        },
        deleteSavedPlaylistWithUndoSuccess: () => {
            actions.deleteLocalPlaylist(values._savedPlaylist)
        },
    })),

    selectors(({ actions }) => ({
        newPlaylistLoading: [(s) => [s._savedPlaylistLoading], (_savedPlaylistLoading) => !!_savedPlaylistLoading],
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
            if (router.values.location.pathname === urls.sessionRecordings(SessionRecordingsTabs.Playlists)) {
                const nextValues = values.filters
                const urlValues = objectClean(router.values.searchParams)
                if (!objectsEqual(nextValues, urlValues)) {
                    return [urls.sessionRecordings(SessionRecordingsTabs.Playlists), nextValues, {}, { replace: false }]
                }
            }
        }
        return {
            loadPlaylists: changeUrl,
            setSavedPlaylistsFilters: changeUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.sessionRecordings(SessionRecordingsTabs.Playlists)]: async (_, searchParams) => {
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
