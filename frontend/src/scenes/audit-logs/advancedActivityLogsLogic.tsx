import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { CountedPaginatedResponse } from 'lib/api'
import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { ADVANCED_ACTIVITY_PAGE_SIZE, FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dateStringToDayJs } from 'lib/utils'

import { ActivityScope } from '~/types'

import type { advancedActivityLogsLogicType } from './advancedActivityLogsLogicType'

export interface DetailFilter {
    operation: 'exact' | 'contains' | 'in'
    value: string | string[]
}

export interface ActiveDetailFilter extends DetailFilter {
    key: string
    fieldPath: string
    isCustom: boolean
}

export interface AdvancedActivityLogFilters {
    start_date?: string
    end_date?: string
    users?: string[]
    scopes?: ActivityScope[]
    activities?: string[]
    detail_filters?: Record<string, DetailFilter>
}

export interface DetailField {
    name: string
    types: string[]
}

export interface ScopeFields {
    fields: DetailField[]
}

export interface AvailableFilters {
    static_filters: {
        users: Array<{ label: string; value: string }>
        scopes: Array<{ value: string }>
        activities: Array<{ value: string }>
    }
    detail_fields?: Record<string, ScopeFields>
}

export interface ExportedAsset {
    id: string
    export_format: string
    created_at: string
    has_content: boolean
    filename: string | null
    expires_after: string
    exception: string | null
    export_context?: {
        path?: string
        method?: string
        filters?: {
            start_date?: string | null
            end_date?: string | null
            users?: string[]
            scopes?: string[]
            activities?: string[]
            detail_filters?: Record<string, DetailFilter>
        }
    }
}

const DEFAULT_FILTERS: AdvancedActivityLogFilters = {
    start_date: '-30d',
    users: [],
    scopes: [],
    activities: [],
    detail_filters: {},
}

const DEFAULT_ACTIVE_FILTERS: ActiveDetailFilter[] = []

export const advancedActivityLogsLogic = kea<advancedActivityLogsLogicType>([
    path(['scenes', 'audit-logs', 'advancedActivityLogsLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        setFilters: (filters: Partial<AdvancedActivityLogFilters>) => ({ filters }),
        clearAllFilters: true,
        setPage: (page: number) => ({ page }),
        exportLogs: (format: 'csv' | 'xlsx' | 'json') => ({ format }),
        loadAvailableFilters: true,
        loadExports: true,
        setActiveTab: (tab: 'logs' | 'exports') => ({ tab }),
        addActiveFilter: (fieldPath: string, isCustom: boolean) => ({ fieldPath, isCustom }),
        updateActiveFilter: (key: string, updates: Partial<ActiveDetailFilter>) => ({ key, updates }),
        removeActiveFilter: (key: string) => ({ key }),
        syncFiltersToAPI: true,
    }),

    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                clearAllFilters: () => DEFAULT_FILTERS,
            },
        ],
        activeFilters: [
            DEFAULT_ACTIVE_FILTERS as ActiveDetailFilter[],
            {
                addActiveFilter: (state, { fieldPath, isCustom }) => {
                    const key = `filter_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
                    return [
                        ...state,
                        {
                            key,
                            fieldPath: isCustom ? '' : fieldPath,
                            operation: 'exact' as const,
                            value: '',
                            isCustom,
                        },
                    ]
                },
                updateActiveFilter: (state, { key, updates }) => {
                    return state.map((filter) => (filter.key === key ? { ...filter, ...updates } : filter))
                },
                removeActiveFilter: (state, { key }) => {
                    return state.filter((filter) => filter.key !== key)
                },
                clearAllFilters: () => DEFAULT_ACTIVE_FILTERS,
            },
        ],
        currentPage: [
            1,
            {
                setPage: (_, { page }) => page,
                setFilters: () => 1,
                addDetailFilter: () => 1,
                updateDetailFilter: () => 1,
                removeDetailFilter: () => 1,
            },
        ],
        activeTab: [
            'logs' as 'logs' | 'exports',
            {
                setActiveTab: (_, { tab }) => tab,
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

                    values.filters.users?.forEach((user) => params.append('users', user))
                    values.filters.scopes?.forEach((scope) => params.append('scopes', scope))
                    values.filters.activities?.forEach((activity) => params.append('activities', activity))

                    if (values.filters.detail_filters && Object.keys(values.filters.detail_filters).length > 0) {
                        params.append('detail_filters', JSON.stringify(values.filters.detail_filters))
                    }

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

        exports: [
            [] as ExportedAsset[],
            {
                loadExports: async () => {
                    const params = new URLSearchParams()
                    params.append('context_path', '/advanced_activity_logs/')

                    const response = await api.get(`api/environments/@current/exports/?${params}`)
                    return response.results || []
                },
            },
        ],
    })),

    selectors(({ actions }) => ({
        isFeatureFlagEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: any): boolean => !!featureFlags[FEATURE_FLAGS.ADVANCED_ACTIVITY_LOGS],
        ],

        hasActiveFilters: [
            (s) => [s.filters],
            (filters: AdvancedActivityLogFilters): boolean => {
                return Boolean(
                    filters.start_date ||
                        filters.end_date ||
                        filters.users?.length ||
                        filters.scopes?.length ||
                        filters.activities?.length ||
                        (filters.detail_filters && Object.keys(filters.detail_filters).length > 0)
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

    listeners(({ actions, values }) => ({
        setPage: () => {
            actions.loadAdvancedActivityLogs()
        },
        setFilters: () => {
            actions.loadAdvancedActivityLogs()
        },
        clearAllFilters: () => {
            actions.loadAdvancedActivityLogs()
        },
        addActiveFilter: ({ fieldPath }) => {
            if (fieldPath === '__add_custom__') {
                actions.addActiveFilter('', true)
                return
            }
            actions.syncFiltersToAPI()
        },
        updateActiveFilter: () => {
            actions.syncFiltersToAPI()
        },
        removeActiveFilter: () => {
            actions.syncFiltersToAPI()
        },
        syncFiltersToAPI: () => {
            const detailFilters: Record<string, DetailFilter> = {}
            values.activeFilters.forEach((filter: ActiveDetailFilter) => {
                if (filter.fieldPath && filter.fieldPath.trim()) {
                    const fieldPath = filter.fieldPath.includes('::')
                        ? filter.fieldPath.split('::')[1]
                        : filter.fieldPath

                    detailFilters[fieldPath] = {
                        operation: filter.operation,
                        value: filter.value,
                    }
                }
            })
            actions.setFilters({ detail_filters: detailFilters })
        },
        exportLogs: async ({ format }) => {
            try {
                const startDate = values.filters.start_date
                    ? dateStringToDayJs(values.filters.start_date)?.toISOString()
                    : undefined
                const endDate = values.filters.end_date
                    ? dateStringToDayJs(values.filters.end_date)?.toISOString()
                    : undefined

                const filtersToExport = {
                    start_date: startDate,
                    end_date: endDate,
                    users: values.filters.users,
                    scopes: values.filters.scopes,
                    activities: values.filters.activities,
                    detail_filters: values.filters.detail_filters,
                }

                await api.create(`api/projects/@current/advanced_activity_logs/export/`, {
                    format,
                    filters: filtersToExport,
                })

                lemonToast.success(`Export started! Your ${format.toUpperCase()} export is being prepared.`)

                actions.loadExports()
                actions.setActiveTab('exports')
            } catch (error) {
                console.error('Export failed:', error)
                lemonToast.error('Failed to start export. Please try again.')
            }
        },
    })),

    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadAvailableFilters()
            actions.loadAdvancedActivityLogs()
            actions.loadExports()

            cache.exportPollingInterval = setInterval(() => {
                actions.loadExports()
            }, 5000)
        },
        beforeUnmount: () => {
            if (cache.exportPollingInterval) {
                clearInterval(cache.exportPollingInterval)
            }
        },
    })),
])
