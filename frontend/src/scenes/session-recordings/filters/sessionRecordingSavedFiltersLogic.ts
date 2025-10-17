import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { objectClean, toParams } from 'lib/utils'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'
import { urls } from 'scenes/urls'

import {
    ReplayTabs,
    SavedSessionRecordingPlaylistsFilters,
    SavedSessionRecordingPlaylistsResult,
    SessionRecordingPlaylistType,
} from '~/types'

import { deletePlaylist } from '../playlist/playlistUtils'
import type { sessionRecordingSavedFiltersLogicType } from './sessionRecordingSavedFiltersLogicType'

export const PLAYLISTS_PER_PAGE = 30

export const DEFAULT_PLAYLIST_FILTERS = {
    createdBy: 'All users',
    page: 1,
    dateFrom: 'all',
}

export const sessionRecordingSavedFiltersLogic = kea<sessionRecordingSavedFiltersLogicType>([
    path(() => ['scenes', 'session-recordings', 'filters', 'sessionRecordingSavedFiltersLogic']),
    connect(() => ({
        actions: [sessionRecordingEventUsageLogic, ['reportRecordingPlaylistCreated']],
    })),
    actions(() => ({
        setSavedPlaylistsFilters: (filters: Partial<SavedSessionRecordingPlaylistsFilters>) => ({
            filters,
        }),
        loadSavedFilters: true,
        updatePlaylist: (
            shortId: SessionRecordingPlaylistType['short_id'],
            properties: Partial<SessionRecordingPlaylistType>
        ) => ({ shortId, properties }),
        deletePlaylist: (playlist: SessionRecordingPlaylistType) => ({ playlist }),
        checkForSavedFilterRedirect: true,
        setAppliedSavedFilter: (appliedSavedFilter: SessionRecordingPlaylistType | null) => ({ appliedSavedFilter }),
    })),
    reducers(() => ({
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
        appliedSavedFilter: [
            null as SessionRecordingPlaylistType | null,
            {
                setAppliedSavedFilter: (_, { appliedSavedFilter }) => appliedSavedFilter,
            },
        ],
        loadSavedFiltersFailed: [
            false,
            {
                loadSavedFilters: () => false,
                loadSavedFiltersSuccess: () => false,
                loadSavedFiltersFailure: () => true,
            },
        ],
    })),
    loaders(({ values, actions }) => ({
        savedFilters: {
            __default: { results: [], count: 0, filters: null } as SavedSessionRecordingPlaylistsResult,
            loadSavedFilters: async (_, breakpoint) => {
                const filters = { ...values.filters }

                const params = {
                    limit: PLAYLISTS_PER_PAGE,
                    offset: Math.max(0, (filters.page - 1) * PLAYLISTS_PER_PAGE),
                    order: '-last_modified_at',
                    created_by: undefined,
                    search: filters.search || undefined,
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
                await deletePlaylist(playlist, () => actions.loadSavedFilters())
                values.playlists.results = values.playlists.results.filter((x) => x.short_id !== playlist.short_id)
                actions.loadSavedFilters()
                return values.playlists
            },
        },
    })),
    listeners(({ actions }) => ({
        setSavedPlaylistsFilters: () => {
            actions.loadSavedFilters()
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
    })),

    selectors(({ actions }) => ({
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
    afterMount(({ actions }) => {
        actions.loadSavedFilters()
        actions.checkForSavedFilterRedirect()
    }),
])
