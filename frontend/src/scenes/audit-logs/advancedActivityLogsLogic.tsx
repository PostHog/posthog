import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api, { CountedPaginatedResponse } from 'lib/api'
import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { ADVANCED_ACTIVITY_PAGE_SIZE, OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dateStringToDayJs, objectClean } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ActivityScope, OrganizationType, TeamBasicType } from '~/types'

import { userLogic } from '../userLogic'
import type { advancedActivityLogsLogicType } from './advancedActivityLogsLogicType'

export type ActivityLogsView = 'project' | 'organization'

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
    clients?: string[]
    team_ids?: number[]
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
        clients: Array<{ value: string }>
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
export const DEFAULT_START_DATE = '-30d'

const DEFAULT_FILTERS: AdvancedActivityLogFilters = {
    start_date: DEFAULT_START_DATE,
    users: [],
    scopes: [],
    activities: [],
    clients: [],
    team_ids: [],
    detail_filters: {},
    item_ids: [],
    page: 1,
}

const ADVANCED_FILTERS = ['was_impersonated', 'is_system', 'item_ids', 'clients', 'detail_filters'] as const

function parseListSearchParam(raw: unknown): string[] {
    if (raw === undefined || raw === null || raw === '') {
        return []
    }
    if (Array.isArray(raw)) {
        return raw.map(String)
    }
    if (typeof raw === 'string') {
        return raw.split(',').filter((v) => v.length > 0)
    }
    return [String(raw)]
}

function parseBooleanSearchParam(raw: unknown): boolean | undefined {
    if (raw === undefined || raw === null) {
        return undefined
    }
    return raw === 'true' || raw === true
}

export const advancedActivityLogsLogic = kea<advancedActivityLogsLogicType>([
    path(['scenes', 'audit-logs', 'advancedActivityLogsLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['hasAvailableFeature'],
            teamLogic,
            ['currentTeamIdStrict', 'currentProjectId'],
            organizationLogic,
            ['currentOrganization', 'currentOrganizationId'],
        ],
    })),

    actions({
        setFilters: (filters: Partial<AdvancedActivityLogFilters>) => ({ filters }),
        setPage: (page: number) => ({ page }),
        clearAllFilters: true,
        setActiveTab: (tab: 'logs' | 'exports') => ({ tab }),
        setShowMoreFilters: (show: boolean) => ({ show }),
        setView: (view: ActivityLogsView) => ({ view }),

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
        view: [
            'project' as ActivityLogsView,
            {
                setView: (_, { view }) => view,
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
                    values.filters.clients?.forEach((client) => params.append('clients', client))
                    values.filters.item_ids?.forEach((item_id) => params.append('item_ids', item_id))
                    if (values.isOrganizationView) {
                        values.filters.team_ids?.forEach((team_id: number) =>
                            params.append('team_ids', String(team_id))
                        )
                    }

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

                    const response = await api.get(`${values.advancedActivityLogsBaseUrl}/?${params}`)
                    return response
                },
            },
        ],

        availableFilters: [
            null as AvailableFilters | null,
            {
                loadAvailableFilters: async () => {
                    const response = await api.get(`${values.advancedActivityLogsBaseUrl}/available_filters/`)
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
                    const response = await api.get(`api/environments/${values.currentTeamIdStrict}/exports/?${params}`)
                    return response.results || []
                },
            },
        ],
    })),

    selectors({
        isOrganizationView: [(s) => [s.view], (view: ActivityLogsView): boolean => view === 'organization'],

        advancedActivityLogsBaseUrl: [
            (s) => [s.isOrganizationView, s.currentProjectId, s.currentOrganizationId],
            (isOrganizationView: boolean, currentProjectId: number | string, currentOrganizationId: string): string =>
                isOrganizationView
                    ? `api/organizations/${currentOrganizationId}/advanced_activity_logs`
                    : `api/projects/${currentProjectId}/advanced_activity_logs`,
        ],

        canViewOrganization: [
            (s) => [s.currentOrganization],
            (currentOrganization: OrganizationType | null): boolean =>
                !!currentOrganization?.membership_level &&
                currentOrganization.membership_level >= OrganizationMembershipLevel.Admin,
        ],

        teamsById: [
            (s) => [s.currentOrganization],
            (currentOrganization: OrganizationType | null): Record<number, string> =>
                Object.fromEntries(
                    (currentOrganization?.teams ?? []).map((team: TeamBasicType) => [team.id, team.name])
                ),
        ],

        hasActiveFilters: [
            (s) => [s.filters, s.isOrganizationView],
            (filters: AdvancedActivityLogFilters, isOrganizationView: boolean): boolean => {
                return Boolean(
                    filters.start_date ||
                    filters.end_date ||
                    filters.users?.length ||
                    filters.scopes?.length ||
                    filters.activities?.length ||
                    filters.clients?.length ||
                    filters.item_ids?.length ||
                    (isOrganizationView && filters.team_ids?.length) ||
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
                if (filters.clients && filters.clients.length > 0) {
                    count++
                }
                if (filters.detail_filters && Object.keys(filters.detail_filters).length > 0) {
                    count++
                }

                return count
            },
        ],

        urlSearchParams: [
            (s) => [s.filters, s.isOrganizationView],
            (filters: AdvancedActivityLogFilters, isOrganizationView: boolean) => {
                return objectClean({
                    ...router.values.searchParams,
                    view: isOrganizationView ? 'organization' : undefined,
                    start_date: filters.start_date,
                    end_date: filters.end_date,
                    users: filters.users?.length ? filters.users.join(',') : undefined,
                    scopes: filters.scopes?.length ? filters.scopes.join(',') : undefined,
                    activities: filters.activities?.length ? filters.activities.join(',') : undefined,
                    clients: filters.clients?.length ? filters.clients.join(',') : undefined,
                    team_ids: isOrganizationView && filters.team_ids?.length ? filters.team_ids.join(',') : undefined,
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
        setView: () => {
            // Switching view changes both the endpoint and the meaning of project filters,
            // so refresh both the static filter options and the log results.
            actions.setFilters({ team_ids: [], page: 1 })
            actions.loadAvailableFilters()
            actions.loadAdvancedActivityLogs({})
        },

        setActiveTab: ({ tab }) => {
            if (tab === 'exports' && !values.isOrganizationView) {
                // Start polling when switching to exports tab (project view only)
                actions.loadExports()
                cache.disposables.add(() => {
                    const intervalId = setInterval(() => {
                        actions.loadExports()
                    }, 5000)
                    return () => clearInterval(intervalId)
                }, 'exportPollingInterval')
            } else {
                // Stop polling when switching away from exports tab (or in organization view)
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
            if (values.isOrganizationView) {
                lemonToast.info('Export is not yet available for organization-wide activity logs.')
                return
            }
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
                    clients: values.filters.clients,
                    detail_filters: values.filters.detail_filters,
                    was_impersonated: values.filters.was_impersonated,
                    is_system: values.filters.is_system,
                    item_ids: values.filters.item_ids,
                }

                await api.create(`api/projects/${values.currentProjectId}/advanced_activity_logs/export/`, {
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

    actionToUrl(({ values }) => {
        const replaceUrl = (): [string, Record<string, any>, Record<string, any>, { replace: true }] => [
            router.values.location.pathname,
            values.urlSearchParams,
            router.values.hashParams,
            { replace: true },
        ]
        return {
            setFilters: replaceUrl,
            setPage: replaceUrl,
            setView: replaceUrl,
            clearAllFilters: replaceUrl,
        }
    }),

    urlToAction(({ actions, values }) => ({
        '/activity-logs': (_, searchParams) => {
            const hasUrlParams = Object.keys(searchParams).length > 0

            const desiredView: ActivityLogsView =
                searchParams.view === 'organization' && values.canViewOrganization ? 'organization' : 'project'
            if (desiredView !== values.view) {
                actions.setView(desiredView)
            }

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

            const users = parseListSearchParam(searchParams.users)
            if (users.length) {
                urlFilters.users = users
            }
            const scopes = parseListSearchParam(searchParams.scopes)
            if (scopes.length) {
                urlFilters.scopes = scopes as ActivityScope[]
            }
            const activities = parseListSearchParam(searchParams.activities)
            if (activities.length) {
                urlFilters.activities = activities
            }
            const clients = parseListSearchParam(searchParams.clients)
            if (clients.length) {
                urlFilters.clients = clients
            }
            const itemIds = parseListSearchParam(searchParams.item_ids)
            if (itemIds.length) {
                urlFilters.item_ids = itemIds
            }
            if (desiredView === 'organization') {
                const teamIds = parseListSearchParam(searchParams.team_ids)
                    .map((v) => parseInt(v, 10))
                    .filter((v) => !Number.isNaN(v))
                if (teamIds.length) {
                    urlFilters.team_ids = teamIds
                }
            }

            const wasImpersonated = parseBooleanSearchParam(searchParams.was_impersonated)
            if (wasImpersonated !== undefined) {
                urlFilters.was_impersonated = wasImpersonated
            }
            const isSystem = parseBooleanSearchParam(searchParams.is_system)
            if (isSystem !== undefined) {
                urlFilters.is_system = isSystem
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
