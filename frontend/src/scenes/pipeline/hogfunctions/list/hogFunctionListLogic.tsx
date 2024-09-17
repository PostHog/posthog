import { lemonToast } from '@posthog/lemon-ui'
import FuseClass from 'fuse.js'
import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { pipelineAccessLogic } from 'scenes/pipeline/pipelineAccessLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { HogFunctionType } from '~/types'

import type { hogFunctionListLogicType } from './hogFunctionListLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFunctionType> {}

export type HogFunctionListFilters = {
    search?: string
    onlyActive?: boolean
    showHidden?: boolean
    filters?: Record<string, any>
}

export type HogFunctionListLogicProps = {
    defaultFilters?: HogFunctionListFilters
    forceFilters?: HogFunctionListFilters
    syncFiltersWithUrl?: boolean
}

export const hogFunctionListLogic = kea<hogFunctionListLogicType>([
    props({} as HogFunctionListLogicProps),
    key((props) => (props.syncFiltersWithUrl ? 'scene' : 'default')),
    path((id) => ['scenes', 'pipeline', 'hogFunctionListLogic', id]),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            pipelineAccessLogic,
            ['canEnableNewDestinations'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    }),
    actions({
        toggleEnabled: (hogFunction: HogFunctionType, enabled: boolean) => ({ hogFunction, enabled }),
        deleteHogFunction: (hogFunction: HogFunctionType) => ({ hogFunction }),
        setFilters: (filters: Partial<HogFunctionListFilters>) => ({ filters }),
        resetFilters: true,
    }),
    reducers(({ props }) => ({
        filters: [
            { ...(props.defaultFilters || {}), ...(props.forceFilters || {}) } as HogFunctionListFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                    ...(props.forceFilters || {}),
                }),
                resetFilters: () => ({
                    ...(props.forceFilters || {}),
                }),
            },
        ],
    })),
    loaders(({ values, actions }) => ({
        _hogFunctions: [
            [] as HogFunctionType[],
            {
                loadHogFunctions: async () => {
                    return (
                        await api.hogFunctions.list({
                            filters: values.filters?.filters,
                        })
                    ).results
                },
                deleteHogFunction: async ({ hogFunction }) => {
                    await deleteWithUndo({
                        endpoint: `projects/${teamLogic.values.currentTeamId}/hog_functions`,
                        object: {
                            id: hogFunction.id,
                            name: hogFunction.name,
                        },
                        callback: (undo) => {
                            if (undo) {
                                actions.loadHogFunctions()
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
            },
        ],
    })),
    selectors({
        loading: [(s) => [s._hogFunctionsLoading], (hogFunctionsLoading) => hogFunctionsLoading],
        hogFunctions: [
            (s) => [s._hogFunctions, s.filters],
            (hogFunctions, filters) =>
                filters.showHidden ? hogFunctions : hogFunctions.filter((hf) => !hf.name.includes('[CDP-TEST-HIDDEN]')),
        ],
        sortedHogFunctions: [
            (s) => [s.hogFunctions],
            (hogFunctions): HogFunctionType[] => {
                const enabledFirst = hogFunctions.sort((a, b) => Number(b.enabled) - Number(a.enabled))
                return enabledFirst
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
            (s) => [s.filters, s.sortedHogFunctions, s.hogFunctionsFuse],
            (filters, hogFunctions, hogFunctionsFuse): HogFunctionType[] => {
                const { search, onlyActive } = filters

                return (search ? hogFunctionsFuse.search(search).map((x) => x.item) : hogFunctions).filter((x) => {
                    if (onlyActive && !x.enabled) {
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
                    return hogFunction?.template?.status === 'free' || canEnableNewDestinations
                }
            },
        ],
    }),

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
