import { lemonToast } from '@posthog/lemon-ui'
import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { pipelineAccessLogic } from 'scenes/pipeline/pipelineAccessLogic'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { CyclotronJobFiltersType, HogFunctionType, HogFunctionTypeType, UserType } from '~/types'

import type { hogFunctionsListLogicType } from './hogFunctionsListLogicType'

export const CDP_TEST_HIDDEN_FLAG = '[CDP-TEST-HIDDEN]'
// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFunctionType> {}

export type HogFunctionListFilters = {
    search?: string
    showPaused?: boolean
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
            pipelineAccessLogic,
            ['canEnableNewDestinations'],
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
                    return (
                        await api.hogFunctions.list({
                            filter_groups: props.forceFilterGroups,
                            types: [props.type, ...(props.additionalTypes || [])],
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
                    if (enabled && !values.canEnableNewDestinations) {
                        lemonToast.error('Data pipelines add-on is required for enabling new destinations.')
                        return values.hogFunctions
                    }

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
            (s) => [s.hogFunctions, (_, props) => props.manualFunctions ?? []],
            (hogFunctions, manualFunctions): HogFunctionType[] => {
                const enabledFirst = [...hogFunctions, ...manualFunctions].sort(
                    (a, b) => Number(b.enabled) - Number(a.enabled)
                )
                return enabledFirst
            },
        ],
        enabledHogFunctions: [
            (s) => [s.hogFunctions],
            (hogFunctions): HogFunctionType[] => {
                return hogFunctions.filter((hogFunction) => hogFunction.enabled)
            },
        ],
        hogFunctionsFuse: [
            (s) => [s.hogFunctions],
            (hogFunctions): Fuse => {
                return new FuseClass(hogFunctions || [], {
                    keys: ['name', 'description'],
                    threshold: 0.3,
                })
            },
        ],

        filteredHogFunctions: [
            (s) => [s.filters, s.sortedHogFunctions, s.hogFunctionsFuse, s.user],
            (filters, hogFunctions, hogFunctionsFuse, user): HogFunctionType[] => {
                const { search, showPaused } = filters

                return (search ? hogFunctionsFuse.search(search).map((x) => x.item) : hogFunctions).filter((x) => {
                    if (!shouldShowHogFunction(x, user)) {
                        return false
                    }

                    if (!showPaused && !x.enabled) {
                        return false
                    }
                    return true
                })
            },
        ],

        canEnableHogFunction: [
            (s) => [s.canEnableNewDestinations],
            (canEnableNewDestinations): ((hogFunction: HogFunctionType) => boolean) => {
                return (hogFunction: HogFunctionType) => {
                    return hogFunction?.template?.free || canEnableNewDestinations
                }
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
            }
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
