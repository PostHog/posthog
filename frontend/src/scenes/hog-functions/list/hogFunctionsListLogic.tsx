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
const EMPTY_MANUAL_FUNCTIONS: HogFunctionType[] = []

export type HogFunctionListFilters = {
    search?: string
    showPaused?: boolean
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
        reorderModalOpen: [
            false as boolean,
            {
                setReorderModalOpen: (_, { open }) => open,
            },
        ],
    })),
    loaders(({ values, actions, props }) => ({
        hogFunctions: [
            [] as HogFunctionType[],
            {
                loadHogFunctions: async () => {
                    const search = values.filters.search?.trim() || undefined
                    return (
                        await api.hogFunctions.list({
                            filter_groups: props.forceFilterGroups,
                            types: [props.type, ...(props.additionalTypes || [])],
                            search,
                            // TODO: This is a temporary fix. We need proper server-side pagination
                            // once we rework the data pipelines UI and batch exports is no longer
                            // part of the same list
                            limit: 300,
                        })
                    ).results
                },
                saveHogFunctionOrder: async ({ newOrders }) => {
                    return await api.hogFunctions.rearrange(newOrders)
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

                    return values.hogFunctions.filter((x) => x.id !== hogFunction.id)
                },
                toggleEnabled: async ({ hogFunction, enabled }) => {
                    const { hogFunctions } = values
                    const hogFunctionIndex = hogFunctions.findIndex((hf) => hf.id === hogFunction.id)
                    const response = await api.hogFunctions.update(hogFunction.id, {
                        enabled,
                    })
                    return [
                        ...hogFunctions.slice(0, hogFunctionIndex),
                        response,
                        ...hogFunctions.slice(hogFunctionIndex + 1),
                    ]
                },
                addHogFunction: ({ hogFunction }) => {
                    return [hogFunction, ...values.hogFunctions]
                },
            },
        ],
    })),
    selectors({
        loading: [(s) => [s.hogFunctionsLoading], (hogFunctionsLoading) => hogFunctionsLoading],
        sortedHogFunctions: [
            (s) => [s.hogFunctions, s.filters, (_, props) => props.manualFunctions ?? EMPTY_MANUAL_FUNCTIONS],
            (
                hogFunctions: HogFunctionType[],
                filters: HogFunctionListFilters,
                manualFunctions: HogFunctionType[]
            ): HogFunctionType[] => {
                const search = filters.search?.trim().toLowerCase()
                const filteredManual = search
                    ? manualFunctions.filter(
                          (f) => f.name?.toLowerCase().includes(search) || f.description?.toLowerCase().includes(search)
                      )
                    : manualFunctions
                const enabledFirst = [...hogFunctions, ...filteredManual].sort(
                    (a, b) => Number(b.enabled) - Number(a.enabled)
                )
                return enabledFirst
            },
        ],
        enabledHogFunctions: [
            (s) => [s.sortedHogFunctions],
            (hogFunctions): HogFunctionType[] => {
                return hogFunctions.filter((hogFunction) => hogFunction.enabled)
            },
        ],
        filteredHogFunctions: [
            (s) => [s.filters, s.sortedHogFunctions, s.user],
            (filters, hogFunctions, user): HogFunctionType[] => {
                const { showPaused, createdBy } = filters

                return hogFunctions.filter((x) => {
                    if (!shouldShowHogFunction(x, user)) {
                        return false
                    }

                    if (!showPaused && !x.enabled) {
                        return false
                    }

                    if (createdBy && x.created_by?.uuid !== createdBy) {
                        return false
                    }

                    return true
                })
            },
        ],

        hiddenHogFunctions: [
            (s) => [s.sortedHogFunctions, s.filteredHogFunctions],
            (sortedHogFunctions, filteredHogFunctions): HogFunctionType[] => {
                return sortedHogFunctions.filter((hogFunction) => !filteredHogFunctions.includes(hogFunction))
            },
        ],
    }),

    listeners(({ actions }) => ({
        setFilters: async ({ filters }, breakpoint) => {
            if (filters.search === undefined) {
                return
            }
            await breakpoint(250)
            actions.loadHogFunctions()
        },
        resetFilters: () => {
            actions.loadHogFunctions()
        },
        saveHogFunctionOrderSuccess: () => {
            actions.setReorderModalOpen(false)
            lemonToast.success('Order updated successfully')
        },
        saveHogFunctionOrderFailure: () => {
            lemonToast.error('Failed to update order')
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
