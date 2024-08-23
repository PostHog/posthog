import FuseClass from 'fuse.js'
import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { pipelineAccessLogic } from 'scenes/pipeline/pipelineAccessLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { HogFunctionTemplateType } from '~/types'

import type { hogFunctionTemplateListLogicType } from './hogFunctionTemplateListLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFunctionTemplateType> {}

export type HogFunctionTemplateListFilters = {
    search?: string
    filters?: Record<string, any>
    subtemplateId?: string
}

export type HogFunctionTemplateListLogicProps = {
    defaultFilters?: HogFunctionTemplateListFilters
    forceFilters?: HogFunctionTemplateListFilters
    syncFiltersWithUrl?: boolean
}

export const hogFunctionTemplateListLogic = kea<hogFunctionTemplateListLogicType>([
    props({} as HogFunctionTemplateListLogicProps),
    key((props) => (props.syncFiltersWithUrl ? 'scene' : 'default')),
    path((id) => ['scenes', 'pipeline', 'destinationsLogic', id]),
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
        setFilters: (filters: Partial<HogFunctionTemplateListFilters>) => ({ filters }),
        resetFilters: true,
    }),
    reducers(({ props }) => ({
        filters: [
            { ...(props.defaultFilters || {}), ...(props.forceFilters || {}) } as HogFunctionTemplateListFilters,
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
    loaders(() => ({
        templates: [
            [] as HogFunctionTemplateType[],
            {
                loadHogFunctionTemplates: async () => {
                    return (await api.hogFunctions.listTemplates()).results
                },
            },
        ],
    })),
    selectors({
        templatesFuse: [
            (s) => [s.templates],
            (hogFunctionTemplates): Fuse => {
                return new FuseClass(hogFunctionTemplates || [], {
                    keys: ['name', 'description'],
                    threshold: 0.3,
                })
            },
        ],

        filteredTemplates: [
            (s) => [s.filters, s.templates, s.templatesFuse],
            (filters, templates, templatesFuse): HogFunctionTemplateType[] => {
                const { search } = filters

                return search ? templatesFuse.search(search).map((x) => x.item) : templates
            },
        ],

        // canEnableHogFunction: [
        //     (s) => [s.canEnableNewDestinations],
        //     (canEnableNewDestinations): ((hogFunction: Ho) => boolean) => {
        //         return (hogFunction: HogFunctionType) => {
        //             return hogFunction?.template?.status === 'free' || canEnableNewDestinations
        //         }
        //     },
        // ],
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
