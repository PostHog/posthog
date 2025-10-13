import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api, { CountedPaginatedResponse } from 'lib/api'
import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { ADVANCED_ACTIVITY_PAGE_SIZE } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dateStringToDayJs, objectClean } from 'lib/utils'

import { ActivityScope } from '~/types'

import { userLogic } from '../userLogic'
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
    was_impersonated?: boolean
    is_system?: boolean
    item_ids?: string[]
    page?: number
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
    export_context?: any
}

// Constants
const DEFAULT_FILTERS: AdvancedActivityLogFilters = {
    start_date: '-30d',
    users: [],
    scopes: [],
    activities: [],
    detail_filters: {},
    item_ids: [],
    page: 1,
}

const ADVANCED_FILTERS = ['was_impersonated', 'is_system', 'item_ids', 'detail_filters'] as const

export const advancedActivityLogsLogic = kea<advancedActivityLogsLogicType>([
    path(['scenes', 'audit-logs', 'advancedActivityLogsLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], userLogic, ['hasAvailableFeature']],
    })),

    actions({
        setFilters: (filters: Partial<AdvancedActivityLogFilters>) => ({ filters }),
        setPage: (page: number) => ({ page }),
        clearAllFilters: true,
        setActiveTab: (tab: 'logs' | 'exports') => ({ tab }),
        setShowMoreFilters: (show: boolean) => ({ show }),

        // Detail filters
        addActiveFilter: (fieldPath: string, isCustom: boolean = false) => ({ fieldPath, isCustom }),
        updateActiveFilter: (key: string, updates: Partial<ActiveDetailFilter>) => ({ key, updates }),
        removeActiveFilter: (key: string) => ({ key }),
        setActiveFilters: (activeFilters: ActiveDetailFilter[]) => ({ activeFilters }),
        syncFiltersToAPI: true,

        // Export
        exportLogs: (format: 'csv' | 'xlsx') => ({ format }),
    }),

    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => objectClean({ ...state, ...filters }),
                setPage: (state, { page }) => ({ ...state, page }),
                clearAllFilters: () => DEFAULT_FILTERS,
            },
        ],
        activeFilters: [
            [] as ActiveDetailFilter[],
            {
                addActiveFilter: (state, { fieldPath, isCustom }) => [
                    ...state,
                    {
                        key: `filter_${Date.now()}`,
                        fieldPath: isCustom ? '' : fieldPath,
                        operation: 'exact' as const,
                        value: '',
                        isCustom,
                    },
                ],
                updateActiveFilter: (state, { key, updates }) =>
                    state.map((filter) => (filter.key === key ? { ...filter, ...updates } : filter)),
                removeActiveFilter: (state, { key }) => state.filter((filter) => filter.key !== key),
                setActiveFilters: (_, { activeFilters }) => activeFilters,
                clearAllFilters: () => [],
            },
        ],
        activeTab: [
            'logs' as 'logs' | 'exports',
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        showMoreFilters: [
            false,
            {
                setShowMoreFilters: (_, { show }) => show,
                setFilters: (state, { filters }) => {
                    const hasAdvancedFilters = ADVANCED_FILTERS.some((key) => {
                        if (key === 'detail_filters') {
                            return filters.detail_filters && Object.keys(filters.detail_filters).length > 0
                        }
                        const value = filters[key]
                        return value !== undefined && value !== null && (Array.isArray(value) ? value.length > 0 : true)
                    })
                    return hasAdvancedFilters ? true : state
                },
            },
        ],
    }),

    loaders(({ values }) => ({
        advancedActivityLogs: [
            { results: [], count: 0 } as CountedPaginatedResponse<ActivityLogItem>,
            {
                loadAdvancedActivityLogs: async (_, breakpoint) => {
                    await breakpoint(300)

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
                    values.filters.item_ids?.forEach((item_id) => params.append('item_ids', item_id))

                    if (values.filters.was_impersonated !== undefined) {
                        params.append('was_impersonated', values.filters.was_impersonated.toString())
                    }
                    if (values.filters.is_system !== undefined) {
                        params.append('is_system', values.filters.is_system.toString())
                    }
                    if (values.filters.detail_filters && Object.keys(values.filters.detail_filters).length > 0) {
                        params.append('detail_filters', JSON.stringify(values.filters.detail_filters))
                    }

                    params.append('page', (values.filters.page || 1).toString())
                    params.append('page_size', ADVANCED_ACTIVITY_PAGE_SIZE.toString())
                    params.append('include_organization_scoped', '1')

                    const response = await api.get(`api/projects/@current/advanced_activity_logs/?${params}`)
                    return response
                },
            },
        ],

        availableFilters: [
            null as AvailableFilters | null,
            {
                loadAvailableFilters: async () => {
                    const response = await api.get(
                        `api/projects/@current/advanced_activity_logs/available_filters/?include_organization_scoped=1`
                    )
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

    selectors({
        hasActiveFilters: [
            (s) => [s.filters],
            (filters: AdvancedActivityLogFilters): boolean => {
                return Boolean(
                    filters.start_date ||
                        filters.end_date ||
                        filters.users?.length ||
                        filters.scopes?.length ||
                        filters.activities?.length ||
                        filters.item_ids?.length ||
                        filters.was_impersonated !== undefined ||
                        filters.is_system !== undefined ||
                        (filters.detail_filters && Object.keys(filters.detail_filters).length > 0)
                )
            },
        ],

        pagination: [
            (s) => [s.filters, s.advancedActivityLogs],
            (filters: AdvancedActivityLogFilters, advancedActivityLogs): PaginationManual => ({
                controlled: true,
                pageSize: ADVANCED_ACTIVITY_PAGE_SIZE,
                currentPage: filters.page || 1,
                entryCount: advancedActivityLogs.count || 0,
                onBackward: () => advancedActivityLogsLogic.actions.setPage((filters.page || 1) - 1),
                onForward: () => advancedActivityLogsLogic.actions.setPage((filters.page || 1) + 1),
            }),
        ],

        activeAdvancedFiltersCount: [
            (s) => [s.filters],
            (filters: AdvancedActivityLogFilters): number => {
                let count = 0

                if (filters.was_impersonated !== undefined) {
                    count++
                }
                if (filters.is_system !== undefined) {
                    count++
                }
                if (filters.item_ids && filters.item_ids.length > 0) {
                    count++
                }
                if (filters.detail_filters && Object.keys(filters.detail_filters).length > 0) {
                    count++
                }

                return count
            },
        ],

        urlSearchParams: [
            (s) => [s.filters],
            (filters: AdvancedActivityLogFilters) => {
                return objectClean({
                    ...router.values.searchParams,
                    start_date: filters.start_date,
                    end_date: filters.end_date,
                    users: filters.users?.length ? filters.users.join(',') : undefined,
                    scopes: filters.scopes?.length ? filters.scopes.join(',') : undefined,
                    activities: filters.activities?.length ? filters.activities.join(',') : undefined,
                    item_ids: filters.item_ids?.length ? filters.item_ids.join(',') : undefined,
                    was_impersonated: filters.was_impersonated?.toString(),
                    is_system: filters.is_system?.toString(),
                    detail_filters:
                        filters.detail_filters && Object.keys(filters.detail_filters).length > 0
                            ? JSON.stringify(filters.detail_filters)
                            : undefined,
                    page: filters.page && filters.page > 1 ? filters.page : undefined,
                })
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        setFilters: async ({ filters }, breakpoint) => {
            // Check if we're setting non-page filters while on page > 1
            const settingNonPageFilters = Object.keys(filters).some((key) => key !== 'page')
            if (settingNonPageFilters && values.filters.page && values.filters.page > 1 && !filters.page) {
                // Reset page to 1 by calling setPage
                actions.setPage(1)
                return
            }

            await breakpoint(300)
            actions.loadAdvancedActivityLogs({})
        },
        setPage: () => {
            actions.loadAdvancedActivityLogs({})
        },
        clearAllFilters: () => {
            actions.setActiveFilters([])
            actions.setShowMoreFilters(false)
            actions.loadAdvancedActivityLogs({})
        },

        setActiveTab: ({ tab }) => {
            if (tab === 'exports') {
                // Start polling when switching to exports tab
                actions.loadExports()
                cache.disposables.add(() => {
                    const intervalId = setInterval(() => {
                        actions.loadExports()
                    }, 5000)
                    return () => clearInterval(intervalId)
                }, 'exportPollingInterval')
            } else {
                // Stop polling when switching away from exports tab
                cache.disposables.dispose('exportPollingInterval')
            }
        },

        // Detail filter management
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
                if (filter.fieldPath?.trim()) {
                    const hasValue = Array.isArray(filter.value)
                        ? filter.value.some((v) => v?.trim())
                        : filter.value?.trim()

                    if (hasValue) {
                        const fieldPath = filter.fieldPath.includes('::')
                            ? filter.fieldPath.split('::')[1]
                            : filter.fieldPath

                        detailFilters[fieldPath] = {
                            operation: filter.operation,
                            value: filter.value,
                        }
                    }
                }
            })
            actions.setFilters({ detail_filters: detailFilters })

            if (Object.keys(detailFilters).length > 0) {
                actions.setShowMoreFilters(true)
            }
        },

        // Handle detail filters from URL
        loadAvailableFiltersSuccess: () => {
            const searchParams = router.values.searchParams
            if (searchParams.detail_filters && values.availableFilters) {
                try {
                    const parsedDetailFilters = JSON.parse(searchParams.detail_filters)
                    const activeFilters = Object.entries(parsedDetailFilters).map(([fieldPath, filter], index) => {
                        let isCustom = true
                        let fullFieldPath = fieldPath

                        if (values.availableFilters?.detail_fields) {
                            // Check General scope first, then other scopes
                            const scopeEntries = Object.entries(values.availableFilters.detail_fields)
                            const generalScope = scopeEntries.find(([scope]) => scope === 'General')
                            const otherScopes = scopeEntries.filter(([scope]) => scope !== 'General')

                            for (const scopeEntry of [generalScope, ...otherScopes].filter(Boolean)) {
                                const [scope, scopeData] = scopeEntry as [string, ScopeFields]
                                const fieldExists = scopeData.fields.some(
                                    (field: DetailField) => field.name === fieldPath
                                )
                                if (fieldExists) {
                                    isCustom = false
                                    fullFieldPath = `${scope}::${fieldPath}`
                                    break
                                }
                            }
                        }

                        // If not found in any scope, keep it as custom
                        if (isCustom) {
                            fullFieldPath = fieldPath
                        }

                        return {
                            key: `url_filter_${index}_${Date.now()}`,
                            fieldPath: fullFieldPath,
                            operation: (filter as DetailFilter).operation,
                            value: (filter as DetailFilter).value,
                            isCustom,
                        }
                    })

                    actions.setActiveFilters(activeFilters)
                    actions.setShowMoreFilters(true)
                } catch (e) {
                    console.error('Failed to parse detail_filters from URL:', e)
                }
            }
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
                    was_impersonated: values.filters.was_impersonated,
                    is_system: values.filters.is_system,
                    item_ids: values.filters.item_ids,
                }

                await api.create('api/projects/@current/advanced_activity_logs/export/?include_organization_scoped=1', {
                    format,
                    filters: filtersToExport,
                })

                lemonToast.success(`Export started! Your ${format.toUpperCase()} export is being prepared.`)
                actions.setActiveTab('exports')
            } catch (error) {
                console.error('Export failed:', error)
                lemonToast.error('Failed to start export. Please try again.')
            }
        },
    })),

    actionToUrl(({ values }) => ({
        setFilters: () => [
            router.values.location.pathname,
            values.urlSearchParams,
            router.values.hashParams,
            { replace: true },
        ],
        setPage: () => [
            router.values.location.pathname,
            values.urlSearchParams,
            router.values.hashParams,
            { replace: true },
        ],
    })),

    urlToAction(({ actions }) => ({
        '/activity-logs': (_, searchParams) => {
            const hasUrlParams = Object.keys(searchParams).length > 0

            // If just visiting the page, we want to clear all filters in case the page was previously mounted with filters
            if (!hasUrlParams) {
                actions.clearAllFilters()
                return
            }

            const urlFilters: Partial<AdvancedActivityLogFilters> = {}

            if (searchParams.start_date) {
                urlFilters.start_date = searchParams.start_date
            }
            if (searchParams.end_date) {
                urlFilters.end_date = searchParams.end_date
            }
            if (searchParams.users) {
                urlFilters.users = Array.isArray(searchParams.users)
                    ? searchParams.users
                    : searchParams.users?.split(',') || []
            }
            if (searchParams.scopes) {
                urlFilters.scopes = (
                    Array.isArray(searchParams.scopes) ? searchParams.scopes : searchParams.scopes?.split(',') || []
                ) as ActivityScope[]
            }
            if (searchParams.activities) {
                urlFilters.activities = Array.isArray(searchParams.activities)
                    ? searchParams.activities
                    : searchParams.activities?.split(',') || []
            }
            if (searchParams.item_ids) {
                urlFilters.item_ids = searchParams.item_ids.split?.(',') || [searchParams.item_ids]
            }
            if (searchParams.was_impersonated !== undefined) {
                urlFilters.was_impersonated =
                    searchParams.was_impersonated === 'true' || searchParams.was_impersonated === true
            }
            if (searchParams.is_system !== undefined) {
                urlFilters.is_system = searchParams.is_system === 'true' || searchParams.is_system === true
            }
            if (searchParams.detail_filters) {
                try {
                    urlFilters.detail_filters = JSON.parse(searchParams.detail_filters)
                } catch (e) {
                    console.error('Failed to parse detail_filters from URL:', e)
                }
            }
            if (searchParams.page) {
                urlFilters.page = parseInt(searchParams.page, 10)
            }

            actions.setFilters(urlFilters)
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadAvailableFilters()
            actions.loadAdvancedActivityLogs({})
        },
    })),
])
