import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api, { PaginatedResponse } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { objectClean, objectsEqual, toParams } from 'lib/utils'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import posthog from 'posthog-js'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'
import { urls } from 'scenes/urls'

import { ReplayTabs, SessionRecordingPlaylistType } from '~/types'

import { createPlaylist, deletePlaylist } from '../playlist/playlistUtils'
import type { savedSessionRecordingPlaylistsLogicType } from './savedSessionRecordingPlaylistsLogicType'

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
    type?: 'collection' | 'saved_filters'
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
    connect(() => ({
        actions: [sessionRecordingEventUsageLogic, ['reportRecordingPlaylistCreated']],
    })),

    actions(() => ({
        setSavedPlaylistsFilters: (filters: Partial<SavedSessionRecordingPlaylistsFilters>) => ({
            filters,
        }),
        loadPlaylists: true,
        loadSavedFilters: true,
        updatePlaylist: (
            shortId: SessionRecordingPlaylistType['short_id'],
            properties: Partial<SessionRecordingPlaylistType>
        ) => ({ shortId, properties }),
        deletePlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
        duplicatePlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
        checkForSavedFilterRedirect: true,
        setSavedFiltersSearch: (search: string) => ({ search }),
        setAppliedSavedFilter: (appliedSavedFilter: SessionRecordingPlaylistType | null) => ({ appliedSavedFilter }),
    })),
    reducers(() => ({
        savedFiltersSearch: [
            '',
            {
                setSavedFiltersSearch: (_, { search }) => search,
            },
        ],
        filters: [
            DEFAULT_PLAYLIST_FILTERS as SavedSessionRecordingPlaylistsFilters | Record<string, any>,
            {
                setSavedPlaylistsFilters: (state, { filters }) =>
                    objectClean({
                        ...Object.fromEntries(Object.entries(state || {}).filter(([key]) => key in filters)),
                        ...filters,
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
        appliedSavedFilter: [
            null as SessionRecordingPlaylistType | null,
            {
                setAppliedSavedFilter: (_, { appliedSavedFilter }) => appliedSavedFilter,
            },
        ],
    })),
    loaders(({ values, actions, props }) => ({
        savedFilters: {
            __default: { results: [], count: 0, filters: null } as SavedSessionRecordingPlaylistsResult,
            loadSavedFilters: async (_, breakpoint) => {
                const filters = { ...values.filters }

                const params = {
                    limit: PLAYLISTS_PER_PAGE,
                    offset: Math.max(0, (filters.page - 1) * PLAYLISTS_PER_PAGE),
                    order: '-last_modified_at',
                    created_by: undefined,
                    search: values.savedFiltersSearch || undefined,
                    date_from: undefined,
                    date_to: undefined,
                    pinned: undefined,
                    type: 'filters',
                }

                const response = await api.recordings.listPlaylists(toParams(params))
                breakpoint()

                return response
            },
        },
        playlists: {
            __default: { results: [], count: 0, filters: null } as SavedSessionRecordingPlaylistsResult,
            loadPlaylists: async (_, breakpoint) => {
                // We do not need to call it on the Home tab anymore
                if (props.tab && props.tab === ReplayTabs.Home) {
                    return { results: [], count: 0, filters: null } as SavedSessionRecordingPlaylistsResult
                }

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
                values.playlists.results = values.playlists.results.filter((x) => x.short_id !== playlist.short_id)
                actions.loadSavedFilters()
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
        setSavedFiltersSearch: () => {
            actions.loadSavedFilters()
        },
        setSavedPlaylistsFilters: () => {
            actions.loadPlaylists()
        },
        checkForSavedFilterRedirect: async () => {
            //If you want to load a saved filter via GET param, you can do it like this: ?savedFilterId=bndnfkxL
            const { savedFilterId } = router.values.searchParams
            if (savedFilterId) {
                const savedFilter = await api.recordings.getPlaylist(savedFilterId)
                if (savedFilter) {
                    router.actions.push(urls.replay(ReplayTabs.Home, savedFilter.filters))
                    actions.setAppliedSavedFilter(savedFilter)
                }
            }
        },
        loadPlaylistsSuccess: ({ playlists }) => {
            try {
                if (!playlists) {
                    return
                }
                // the feature flag might be off, so we don't show the count column
                // but we want to know if we _would_ have shown counts
                // so we'll emit a posthog event
                const playlistTotal = playlists.results.length
                const savedFiltersWithCounts = playlists.results.filter(
                    (playlist) => playlist.recordings_counts?.saved_filters?.count !== null
                ).length
                const collectionWithCounts = playlists.results.filter(
                    (playlist) => playlist.recordings_counts?.collection.count !== null
                ).length
                posthog.capture('session_recordings_playlist_counts', {
                    playlistTotal,
                    savedFiltersWithCounts,
                    collectionWithCounts,
                })
            } catch (e) {
                posthog.captureException(e, { posthog_feature: 'playlist_counting' })
            }
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
        paginationSavedFilters: [
            (s) => [s.filters, s.savedFilters],
            (filters, savedFilters): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: PLAYLISTS_PER_PAGE,
                    currentPage: filters.page,
                    entryCount: savedFilters.count,
                    onBackward: savedFilters.previous
                        ? () => {
                              actions.setSavedPlaylistsFilters({
                                  page: filters.page - 1,
                              })
                              actions.loadSavedFilters()
                          }
                        : undefined,
                    onForward: savedFilters.next
                        ? () => {
                              actions.setSavedPlaylistsFilters({
                                  page: filters.page + 1,
                              })
                              actions.loadSavedFilters()
                          }
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
            if (removeProjectIdIfPresent(router.values.location.pathname) === urls.replay(ReplayTabs.Playlists)) {
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
        [urls.replay(ReplayTabs.Home)]: (_, searchParams) => {
            const currentFilters = values.filters
            const nextFilters = objectClean(searchParams)
            if (!objectsEqual(currentFilters, nextFilters)) {
                actions.setSavedPlaylistsFilters(nextFilters)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        //only call saved filters on the Home tab
        // TODO: Separate to another logic on step 2 @veryayskiy
        if (props.tab && props.tab === ReplayTabs.Home) {
            actions.loadSavedFilters()
            actions.checkForSavedFilterRedirect()
        }

        actions.loadPlaylists()
    }),
])
