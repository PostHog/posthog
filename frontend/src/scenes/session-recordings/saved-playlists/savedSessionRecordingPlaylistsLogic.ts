import { actions, kea, reducers, path, selectors, key, props } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { toParams } from 'lib/utils'
import { SessionRecordingsTabs, SessionRecordingPlaylistType } from '~/types'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { dayjs } from 'lib/dayjs'
import type { savedSessionRecordingPlaylistsLogicType } from './savedSessionRecordingPlaylistsLogicType'

export const PLAYLISTS_PER_PAGE = 30

export interface SavedSessionRecordingPlaylistsResult extends PaginatedResponse<SessionRecordingPlaylistType> {
    count: number
    /** not in the API response */
    filters?: SavedSessionRecordingPlaylistsFilters | null
}

export interface SavedSessionRecordingPlaylistsFilters {
    order: string
    tab: SessionRecordingsTabs
    search: string
    createdBy: number | 'All users'
    dateFrom: string | dayjs.Dayjs | undefined | 'all' | null
    dateTo: string | dayjs.Dayjs | undefined | null
    page: number
}

export interface SavedSessionRecordingPlaylistsLogicProps {
    tab: SessionRecordingsTabs
}

function cleanFilters(values: Partial<SavedSessionRecordingPlaylistsFilters>): SavedSessionRecordingPlaylistsFilters {
    return {
        order: values.order || '-last_modified_at', // Sync with `sorting` selector
        tab: values.tab || SessionRecordingsTabs.Recent,
        search: String(values.search || ''),
        createdBy: (values.tab !== SessionRecordingsTabs.Yours && values.createdBy) || 'All users',
        dateFrom: values.dateFrom || 'all',
        dateTo: values.dateTo || undefined,
        page: parseInt(String(values.page)) || 1,
    }
}

export const savedSessionRecordingPlaylistsLogic = kea<savedSessionRecordingPlaylistsLogicType>([
    path(['scenes', 'session-recordings', 'saved-playlists', 'savedSessionRecordingPlaylistsLogic']),
    props({} as SavedSessionRecordingPlaylistsLogicProps),
    key((props) => props.tab),
    actions(() => ({
        setSavedPlaylistsFilters: (filters: Partial<SavedSessionRecordingPlaylistsFilters>, merge = true) => ({
            filters,
            merge,
        }),
    })),
    reducers(() => ({
        filters: [
            {} as SavedSessionRecordingPlaylistsFilters | Record<string, any>,
            {
                setSavedPlaylistsFilters: (state, { filters, merge }) =>
                    cleanFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        // Reset page on filter change EXCEPT if it's page or view that's being updated
                        ...('page' in filters || 'layoutView' in filters ? {} : { page: 1 }),
                    }),
            },
        ],
    })),
    loaders(({ values }) => ({
        playlists: {
            __default: { results: [], count: 0, filters: null } as SavedSessionRecordingPlaylistsResult,
            loadInsights: async (_, breakpoint) => {
                if (values.playlists.filters !== null) {
                    await breakpoint(300)
                }
                const response = await api.recordings.listPlaylists(
                    toParams({ ...values.paramsFromFilters, basic: true })
                )

                if (values.filters?.search && String(values.filters?.search).match(/^[0-9]+$/)) {
                    try {
                        const playlist: SessionRecordingPlaylistType = await api.recordings.getPlaylist(
                            values.filters.search
                        )
                        return {
                            ...response,
                            count: response.count + 1,
                            results: [playlist, ...response.results],
                        }
                    } catch (e) {
                        // no insight with this ID found, discard
                    }
                }

                // scroll to top if the page changed, except if changed via back/forward
                if (
                    router.values.location.pathname === urls.sessionRecordings() &&
                    router.values.lastMethod !== 'POP' &&
                    values.playlists.filters?.page !== values.filters.page
                ) {
                    window.scrollTo(0, 0)
                }

                return { ...response, filters: values.filters }
            },
        },
    })),
    selectors(() => ({
        paramsFromFilters: [
            (s) => [s.filters],
            (filters) => ({
                order: filters.order,
                limit: PLAYLISTS_PER_PAGE,
                offset: Math.max(0, (filters.page - 1) * PLAYLISTS_PER_PAGE),
                saved: true,
                ...(filters.tab === SessionRecordingsTabs.Yours && { user: true }),
                ...(filters.tab === SessionRecordingsTabs.Pinned && { pinned: true }),
                ...(filters.search && { search: filters.search }),
                ...(filters.createdBy !== 'All users' && { created_by: filters.createdBy }),
                ...(filters.dateFrom &&
                    filters.dateFrom !== 'all' && {
                        date_from: filters.dateFrom,
                        date_to: filters.dateTo,
                    }),
            }),
        ],
    })),
])
