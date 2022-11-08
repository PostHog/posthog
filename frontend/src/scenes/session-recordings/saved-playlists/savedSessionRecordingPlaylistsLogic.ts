import { actions, kea, reducers, path, selectors, key, props, afterMount, listeners } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { toParams } from 'lib/utils'
import { SessionRecordingsTabs, SessionRecordingPlaylistType } from '~/types'
import { dayjs } from 'lib/dayjs'
import type { savedSessionRecordingPlaylistsLogicType } from './savedSessionRecordingPlaylistsLogicType'
import { Sorting } from 'lib/components/LemonTable'
import { PaginationManual } from 'lib/components/PaginationControl'

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

export const savedSessionRecordingPlaylistsLogic = kea<savedSessionRecordingPlaylistsLogicType>([
    path(['scenes', 'session-recordings', 'saved-playlists', 'savedSessionRecordingPlaylistsLogic']),
    props({} as SavedSessionRecordingPlaylistsLogicProps),
    key((props) => props.tab),
    actions(() => ({
        setSavedPlaylistsFilters: (filters: Partial<SavedSessionRecordingPlaylistsFilters>) => ({
            filters,
        }),
        loadPlaylists: true,
    })),
    reducers(({}) => ({
        filters: [
            {
                createdBy: 'All users',
                page: 1,
            } as SavedSessionRecordingPlaylistsFilters | Record<string, any>,
            {
                setSavedPlaylistsFilters: (state, { filters }) => ({
                    ...(state || {}),
                    ...filters,
                    // Reset page on filter change EXCEPT if it's page that's being updated
                    ...('page' in filters ? {} : { page: 1 }),
                }),
            },
        ],
    })),
    loaders(({ values }) => ({
        playlists: {
            __default: { results: [], count: 0, filters: null } as SavedSessionRecordingPlaylistsResult,
            loadPlaylists: async (_, breakpoint) => {
                if (values.playlists.filters !== null) {
                    await breakpoint(300)
                }

                const filters = values.filters
                const createdBy = filters.createdBy === 'All users' ? undefined : filters.createdBy

                const params = {
                    limit: PLAYLISTS_PER_PAGE,
                    offset: Math.max(0, (filters.page - 1) * PLAYLISTS_PER_PAGE),
                    order: filters.order || '-last_modified_at', // Sync with `sorting` selector
                    created_by: createdBy || undefined,
                    search: filters.search || undefined,
                    date_from: filters.dateFrom || 'all',
                    date_to: filters.dateTo || undefined,
                    pinned: filters.pinned ? true : undefined,
                }

                const response = await api.recordings.listPlaylists(toParams(params))

                return response
            },
        },
    })),
    listeners(({ actions }) => ({
        setSavedPlaylistsFilters: async () => {
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

    afterMount(async ({ actions }) => {
        actions.loadPlaylists()
    }),
])
