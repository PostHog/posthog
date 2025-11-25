import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { CyclotronJobFiltersType, HogFunctionType, HogFunctionTypeType, UserType } from '~/types'

import type { hogFunctionsListLogicType } from './hogFunctionsListLogicType'

export const CDP_TEST_HIDDEN_FLAG = '[CDP-TEST-HIDDEN]'

export type HogFunctionListFilters = {
    activeSearch?: string
    pausedSearch?: string
}

export type HogFunctionListPagination = {
    offset: number
    limit: number
}

export type HogFunctionTableType = 'active' | 'paused'

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
        setPagination: (tableType: HogFunctionTableType, pagination: Partial<HogFunctionListPagination>) => ({
            tableType,
            pagination,
        }),
    }),
    reducers(() => ({
        filters: [
            {} as HogFunctionListFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                resetFilters: () => ({}),
            },
        ],
        activePagination: [
            { offset: 0, limit: 10 } as HogFunctionListPagination,
            {
                setPagination: (state, { tableType, pagination }) =>
                    tableType === 'active' ? { ...state, ...pagination } : state,
                setFilters: () => ({ offset: 0, limit: 10 }),
                resetFilters: () => ({ offset: 0, limit: 10 }),
            },
        ],
        pausedPagination: [
            { offset: 0, limit: 10 } as HogFunctionListPagination,
            {
                setPagination: (state, { tableType, pagination }) =>
                    tableType === 'paused' ? { ...state, ...pagination } : state,
                setFilters: () => ({ offset: 0, limit: 10 }),
                resetFilters: () => ({ offset: 0, limit: 10 }),
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
        activeHogFunctionsData: [
            { results: [] as HogFunctionType[], count: 0 },
            {
                loadActiveHogFunctions: async () => {
                    const response = await api.hogFunctions.list({
                        filter_groups: props.forceFilterGroups,
                        types: [props.type, ...(props.additionalTypes || [])],
                        limit: values.activePagination.limit,
                        offset: values.activePagination.offset,
                        search: values.filters.activeSearch,
                        enabled: true,
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
                                actions.loadActiveHogFunctions()
                                actions.loadPausedHogFunctions()
                                refreshTreeItem('hog_function/', hogFunction.id)
                            } else {
                                deleteFromTree('hog_function/', hogFunction.id)
                            }
                        },
                    })

                    const updatedResults = values.activeHogFunctionsData.results.filter((x) => x.id !== hogFunction.id)
                    return {
                        ...values.activeHogFunctionsData,
                        results: updatedResults,
                        count: values.activeHogFunctionsData.count - 1,
                    }
                },
                toggleEnabled: async ({ hogFunction, enabled }) => {
                    await api.hogFunctions.update(hogFunction.id, {
                        enabled,
                    })
                    // Reload both tables since toggling moves items between them
                    actions.loadActiveHogFunctions()
                    actions.loadPausedHogFunctions()
                    return values.activeHogFunctionsData
                },
                addHogFunction: ({ hogFunction }) => {
                    if (hogFunction.enabled) {
                        return {
                            results: [hogFunction, ...values.activeHogFunctionsData.results],
                            count: values.activeHogFunctionsData.count + 1,
                        }
                    }
                    return values.activeHogFunctionsData
                },
            },
        ],
        pausedHogFunctionsData: [
            { results: [] as HogFunctionType[], count: 0 },
            {
                loadPausedHogFunctions: async () => {
                    const response = await api.hogFunctions.list({
                        filter_groups: props.forceFilterGroups,
                        types: [props.type, ...(props.additionalTypes || [])],
                        limit: values.pausedPagination.limit,
                        offset: values.pausedPagination.offset,
                        search: values.filters.pausedSearch,
                        enabled: false,
                    })
                    return { results: response.results, count: response.count }
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
        activeHogFunctions: [(s) => [s.activeHogFunctionsData], (data) => data.results],
        pausedHogFunctions: [(s) => [s.pausedHogFunctionsData], (data) => data.results],
        activeTotalCount: [(s) => [s.activeHogFunctionsData], (data) => data.count],
        pausedTotalCount: [(s) => [s.pausedHogFunctionsData], (data) => data.count],
        loading: [
            (s) => [s.activeHogFunctionsDataLoading, s.pausedHogFunctionsDataLoading],
            (activeLoading, pausedLoading) => activeLoading || pausedLoading,
        ],
        activeLoading: [(s) => [s.activeHogFunctionsDataLoading], (loading) => loading],
        pausedLoading: [(s) => [s.pausedHogFunctionsDataLoading], (loading) => loading],
        // Combined list for backwards compatibility
        hogFunctions: [
            (s) => [s.activeHogFunctions, s.pausedHogFunctions],
            (active, paused): HogFunctionType[] => [...active, ...paused],
        ],
        filteredActiveHogFunctions: [
            (s) => [s.activeHogFunctions, s.user, (_, props) => props.manualFunctions ?? []],
            (
                hogFunctions: HogFunctionType[],
                user: UserType | null,
                manualFunctions: HogFunctionType[]
            ): HogFunctionType[] => {
                // Add manual functions if they're enabled
                const enabledManual = manualFunctions.filter((f: HogFunctionType) => f.enabled)
                return [...hogFunctions, ...enabledManual].filter((x) => shouldShowHogFunction(x, user))
            },
        ],
        filteredPausedHogFunctions: [
            (s) => [s.pausedHogFunctions, s.user, (_, props) => props.manualFunctions ?? []],
            (
                hogFunctions: HogFunctionType[],
                user: UserType | null,
                manualFunctions: HogFunctionType[]
            ): HogFunctionType[] => {
                // Add manual functions if they're paused
                const pausedManual = manualFunctions.filter((f: HogFunctionType) => !f.enabled)
                return [...hogFunctions, ...pausedManual].filter((x) => shouldShowHogFunction(x, user))
            },
        ],
        // Enabled hog functions for order modal (just uses active functions)
        enabledHogFunctions: [
            (s) => [s.filteredActiveHogFunctions],
            (activeHogFunctions: HogFunctionType[]): HogFunctionType[] => activeHogFunctions,
        ],
    }),

    listeners(({ actions }) => ({
        saveHogFunctionOrderSuccess: () => {
            actions.setReorderModalOpen(false)
            lemonToast.success('Order updated successfully')
        },
        saveHogFunctionOrderFailure: () => {
            lemonToast.error('Failed to update order')
        },
        setFilters: ({ filters }) => {
            // Only reload the table whose search changed
            if (filters.activeSearch !== undefined) {
                actions.loadActiveHogFunctions()
            }
            if (filters.pausedSearch !== undefined) {
                actions.loadPausedHogFunctions()
            }
        },
        setPagination: ({ tableType }) => {
            if (tableType === 'active') {
                actions.loadActiveHogFunctions()
            } else {
                actions.loadPausedHogFunctions()
            }
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
                actions.setFilters(searchParams)
            }
        },
    })),
])
