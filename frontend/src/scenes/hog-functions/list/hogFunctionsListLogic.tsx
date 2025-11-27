import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { CyclotronJobFiltersType, HogFunctionType, HogFunctionTypeType, UserType } from '~/types'

import type { hogFunctionsListLogicType } from './hogFunctionsListLogicType'

export const CDP_TEST_HIDDEN_FLAG = '[CDP-TEST-HIDDEN]'

export type HogFunctionListFilters = {
    search?: string
    showPaused?: boolean
    statusFilter?: 'all' | 'active' | 'paused'
    createdBy?: string | null
}

export type HogFunctionListPagination = {
    offset: number
    limit: number
    order?: string
    createdBy?: string | null
}

export type HogFunctionListLogicProps = {
    logicKey?: string
    type: HogFunctionTypeType
    additionalTypes?: HogFunctionTypeType[]
    forceFilterGroups?: CyclotronJobFiltersType[]
    syncFiltersWithUrl?: boolean
    manualFunctions?: HogFunctionType[]
}

export const shouldShowHogFunction = (hogFunction: HogFunctionType, user?: UserType | null): boolean => {
    if (!user) {
        return false
    }
    if (hogFunction.name.includes(CDP_TEST_HIDDEN_FLAG) && !user.is_impersonated && !user.is_staff) {
        return false
    }
    return true
}

export const urlForHogFunction = (hogFunction: HogFunctionType): string => {
    if (hogFunction.id.startsWith('plugin-')) {
        return urls.legacyPlugin(hogFunction.id.replace('plugin-', ''))
    }
    if (hogFunction.id.startsWith('batch-export-')) {
        return urls.batchExport(hogFunction.id.replace('batch-export-', ''))
    }
    return urls.hogFunction(hogFunction.id)
}

export const hogFunctionsListLogic = kea<hogFunctionsListLogicType>([
    props({} as HogFunctionListLogicProps),
    key((props) =>
        JSON.stringify({
            ...props,
            manualFunctions: null, // We don't care about these
        })
    ),
    path((id) => ['scenes', 'pipeline', 'hogFunctionsListLogic', id]),
    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions({
        toggleEnabled: (hogFunction: HogFunctionType, enabled: boolean) => ({ hogFunction, enabled }),
        deleteHogFunction: (hogFunction: HogFunctionType) => ({ hogFunction }),
        setFilters: (filters: Partial<HogFunctionListFilters>) => ({ filters }),
        resetFilters: true,
        addHogFunction: (hogFunction: HogFunctionType) => ({ hogFunction }),
        setReorderModalOpen: (open: boolean) => ({ open }),
        saveHogFunctionOrder: (newOrders: Record<string, number>) => ({ newOrders }),
        setPagination: (pagination: Partial<HogFunctionListPagination>) => ({ pagination }),
        setSearchValue: (value: string) => ({ value }),
        setShowPaused: (showPaused: boolean) => ({ showPaused }),
        setStatusFilter: (statusFilter: 'all' | 'active' | 'paused') => ({ statusFilter }),
    }),
    reducers(() => ({
        filters: [
            { statusFilter: 'active' } as HogFunctionListFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                setSearchValue: (state, { value }) => ({
                    ...state,
                    search: value,
                }),
                setShowPaused: (state, { showPaused }) => ({
                    ...state,
                    showPaused,
                }),
                setStatusFilter: (state, { statusFilter }) => ({
                    ...state,
                    statusFilter,
                }),
            },
        ],
        pagination: [
            { offset: 0, limit: 10 } as HogFunctionListPagination,
            {
                setPagination: (state, { pagination }) => ({ ...state, ...pagination }),
            },
        ],
        reorderModalOpen: [
            false as boolean,
            {
                setReorderModalOpen: (_, { open }) => open,
            },
        ],
    })),
    loaders(({ values, actions, props }) => ({
        hogFunctionsData: [
            { results: [] as HogFunctionType[], count: 0 },
            {
                loadHogFunctions: async () => {
                    const response = await api.hogFunctions.list({
                        filter_groups: props.forceFilterGroups,
                        types: [props.type, ...(props.additionalTypes || [])],
                        limit: values.pagination.limit,
                        offset: values.pagination.offset,
                        search: values.filters.search,
                        order: values.pagination.order,
                        enabled:
                            values.filters.statusFilter === 'paused'
                                ? false
                                : values.filters.statusFilter === 'active'
                                  ? true
                                  : undefined,
                    })
                    return { results: response.results, count: response.count }
                },
                deleteHogFunction: async ({ hogFunction }) => {
                    await deleteWithUndo({
                        endpoint: `projects/${values.currentProjectId}/hog_functions`,
                        object: {
                            id: hogFunction.id,
                            name: hogFunction.name,
                        },
                        callback: (undo) => {
                            if (undo) {
                                actions.loadHogFunctions()
                                refreshTreeItem('hog_function/', hogFunction.id)
                            } else {
                                deleteFromTree('hog_function/', hogFunction.id)
                            }
                        },
                    })

                    const updatedResults = values.hogFunctionsData.results.filter((x) => x.id !== hogFunction.id)
                    return {
                        ...values.hogFunctionsData,
                        results: updatedResults,
                        count: values.hogFunctionsData.count - 1,
                    }
                },
                toggleEnabled: async ({ hogFunction, enabled }) => {
                    const updatedHogFunction = await api.hogFunctions.update(hogFunction.id, {
                        enabled,
                    })

                    const updatedResults = values.hogFunctionsData.results.map((x) =>
                        x.id === hogFunction.id ? updatedHogFunction : x
                    )

                    return {
                        ...values.hogFunctionsData,
                        results: updatedResults,
                    }
                },
                addHogFunction: ({ hogFunction }) => {
                    return {
                        results: [hogFunction, ...values.hogFunctionsData.results],
                        count: values.hogFunctionsData.count + 1,
                    }
                },
            },
        ],
        savedHogFunctionOrder: [
            [] as HogFunctionType[],
            {
                saveHogFunctionOrder: async ({ newOrders }) => {
                    return await api.hogFunctions.rearrange(newOrders)
                },
            },
        ],
    })),
    selectors({
        hogFunctions: [(s) => [s.hogFunctionsData], (data) => data.results],
        totalCount: [(s) => [s.hogFunctionsData], (data) => data.count],
        loading: [(s) => [s.hogFunctionsDataLoading], (loading) => loading],

        filteredHogFunctions: [
            (s) => [s.hogFunctions, s.user, s.filters, (_, props) => props.manualFunctions ?? []],
            (
                hogFunctions: HogFunctionType[],
                user: UserType | null,
                filters: HogFunctionListFilters,
                manualFunctions: HogFunctionType[]
            ): HogFunctionType[] => {
                const { createdBy } = filters
                return [...hogFunctions, ...manualFunctions].filter((x) => {
                    if (!shouldShowHogFunction(x, user)) {
                        return false
                    }
                    if (createdBy && x.created_by?.uuid !== createdBy) {
                        return false
                    }
                    return true
                })
            },
        ],

        // Enabled hog functions for order modal (just uses active functions)
        enabledHogFunctions: [
            (s) => [s.filteredHogFunctions],
            (hogFunctions: HogFunctionType[]): HogFunctionType[] => hogFunctions.filter((x) => x.enabled),
        ],
        // Pagination helpers
        currentPage: [
            (s) => [s.pagination],
            (pagination: HogFunctionListPagination) => Math.floor(pagination.offset / pagination.limit) + 1,
        ],
        showPaused: [(s) => [s.filters], (filters: HogFunctionListFilters) => Boolean(filters.showPaused)],
        statusFilter: [(s) => [s.filters], (filters: HogFunctionListFilters) => filters.statusFilter || 'active'],
        searchValue: [(s) => [s.filters], (filters: HogFunctionListFilters) => filters.search || ''],
    }),

    listeners(({ actions, cache }) => ({
        saveHogFunctionOrderSuccess: () => {
            actions.setReorderModalOpen(false)
            lemonToast.success('Order updated successfully')
        },
        saveHogFunctionOrderFailure: () => {
            lemonToast.error('Failed to update order')
        },
        setFilters: () => {
            actions.loadHogFunctions()
        },
        setPagination: () => {
            actions.loadHogFunctions()
        },
        // Handle debounced search
        setSearchValue: async ({ value }, breakpoint) => {
            if (cache.searchTimeout) {
                clearTimeout(cache.searchTimeout)
            }
            await breakpoint(300)
            actions.setFilters({ search: value })
        },
        setShowPaused: () => {
            actions.loadHogFunctions()
        },
        setStatusFilter: () => {
            actions.setPagination({ offset: 0 })
            actions.loadHogFunctions()
        },
    })),

    actionToUrl(({ props, values }) => {
        if (!props.syncFiltersWithUrl) {
            return {}
        }
        const urlFromFilters = (): [
            string,
            Record<string, any>,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => [
            router.values.location.pathname,
            values.filters,
            router.values.hashParams,
            {
                replace: true,
            },
        ]

        return {
            setFilters: () => urlFromFilters(),
            resetFilters: () => urlFromFilters(),
        }
    }),

    urlToAction(({ props, actions, values }) => ({
        '*': (_, searchParams) => {
            if (!props.syncFiltersWithUrl) {
                return
            }

            if (!objectsEqual(values.filters, searchParams)) {
                const { activeSearch, pausedSearch, page, ...rest } = searchParams
                const filters = { ...rest }
                if (activeSearch) {
                    filters.search = activeSearch
                } else if (pausedSearch) {
                    filters.search = pausedSearch
                }
                if (page) {
                    actions.setPagination({ offset: (Number(page) - 1) * values.pagination.limit })
                }
                actions.setFilters(filters)
            }
        },
    })),
])
