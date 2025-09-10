import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { CountedPaginatedResponse } from 'lib/api'
import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { ADVANCED_ACTIVITY_PAGE_SIZE, FEATURE_FLAGS } from 'lib/constants'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dateStringToDayJs } from 'lib/utils'

import { ActivityScope } from '~/types'

import type { advancedActivityLogsLogicType } from './advancedActivityLogsLogicType'

export interface AdvancedActivityLogFilters {
    start_date: string | null
    end_date: string | null
    users: string[]
    scopes: ActivityScope[]
    activities: string[]
}

export interface AvailableFilters {
    static_filters: {
        users: Array<{ label: string; value: string }>
        scopes: Array<{ value: string }>
        activities: Array<{ value: string }>
    }
}

const DEFAULT_FILTERS: AdvancedActivityLogFilters = {
    start_date: null,
    end_date: null,
    users: [],
    scopes: [],
    activities: [],
}

export const advancedActivityLogsLogic = kea<advancedActivityLogsLogicType>([
    path(['scenes', 'audit-logs', 'advancedActivityLogsLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        setFilters: (filters: Partial<AdvancedActivityLogFilters>) => ({ filters }),
        clearAllFilters: true,
        setPage: (page: number) => ({ page }),
        exportLogs: (format: 'csv' | 'json') => ({ format }),
        loadAvailableFilters: true,
    }),

    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                clearAllFilters: () => DEFAULT_FILTERS,
            },
        ],
        currentPage: [
            1,
            {
                setPage: (_, { page }) => page,
                setFilters: () => 1,
            },
        ],
    }),

    loaders(({ values }) => ({
        advancedActivityLogs: [
            { results: [], count: 0 } as CountedPaginatedResponse<ActivityLogItem>,
            {
                loadAdvancedActivityLogs: async () => {
                    const params = new URLSearchParams()

                    if (values.filters.start_date) {
                        const startDate = dateStringToDayJs(values.filters.start_date)
                        if (startDate) {
                            params.append('start_date', startDate.toISOString())
                        }
                    }
                    if (values.filters.end_date) {
                        const endDate = dateStringToDayJs(values.filters.end_date)
                        if (endDate) {
                            params.append('end_date', endDate.toISOString())
                        }
                    }

                    values.filters.users.forEach((user) => params.append('users', user))
                    values.filters.scopes.forEach((scope) => params.append('scopes', scope))
                    values.filters.activities.forEach((activity) => params.append('activities', activity))

                    params.append('page', values.currentPage.toString())
                    params.append('page_size', ADVANCED_ACTIVITY_PAGE_SIZE.toString())

                    const response = await api.get(`api/projects/@current/advanced_activity_logs/?${params}`)
                    return response
                },
            },
        ],

        availableFilters: [
            null as AvailableFilters | null,
            {
                loadAvailableFilters: async () => {
                    const response = await api.get(`api/projects/@current/advanced_activity_logs/available_filters/`)
                    return response
                },
            },
        ],
    })),

    selectors(({ actions }) => ({
        isFeatureFlagEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.ADVANCED_ACTIVITY_LOGS],
        ],

        hasActiveFilters: [
            (s) => [s.filters],
            (filters: AdvancedActivityLogFilters): boolean => {
                return (
                    filters.start_date !== null ||
                    filters.end_date !== null ||
                    filters.users.length > 0 ||
                    filters.scopes.length > 0 ||
                    filters.activities.length > 0
                )
            },
        ],

        pagination: [
            (s) => [s.currentPage, s.advancedActivityLogs],
            (
                currentPage: number,
                advancedActivityLogs: CountedPaginatedResponse<ActivityLogItem>
            ): PaginationManual => ({
                controlled: true,
                pageSize: ADVANCED_ACTIVITY_PAGE_SIZE,
                currentPage,
                entryCount: advancedActivityLogs.count || 0,
                onBackward: () => actions.setPage(currentPage - 1),
                onForward: () => actions.setPage(currentPage + 1),
            }),
        ],
    })),

    listeners(({ actions }) => ({
        setPage: () => {
            actions.loadAdvancedActivityLogs()
        },
        setFilters: () => {
            actions.loadAdvancedActivityLogs()
        },
        clearAllFilters: () => {
            actions.loadAdvancedActivityLogs()
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadAvailableFilters()
            actions.loadAdvancedActivityLogs()
        },
    })),
])
