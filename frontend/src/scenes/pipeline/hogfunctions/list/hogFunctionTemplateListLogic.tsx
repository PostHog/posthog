import FuseClass from 'fuse.js'
import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { hogFunctionNewUrl } from 'scenes/pipeline/hogfunctions/urls'
import { pipelineAccessLogic } from 'scenes/pipeline/pipelineAccessLogic'

import { HogFunctionTemplateType, HogFunctionTypeType } from '~/types'

import type { hogFunctionTemplateListLogicType } from './hogFunctionTemplateListLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFunctionTemplateType> {}

export type HogFunctionTemplateListFilters = {
    search?: string
    filters?: Record<string, any>
    subTemplateId?: string
}

export type HogFunctionTemplateListLogicProps = {
    type: HogFunctionTypeType
    defaultFilters?: HogFunctionTemplateListFilters
    forceFilters?: HogFunctionTemplateListFilters
    syncFiltersWithUrl?: boolean
}

export const hogFunctionTemplateListLogic = kea<hogFunctionTemplateListLogicType>([
    props({} as HogFunctionTemplateListLogicProps),
    key((props) => `${props.syncFiltersWithUrl ? 'scene' : 'default'}/${props.type ?? 'destination'}`),
    path((id) => ['scenes', 'pipeline', 'destinationsLogic', id]),
    connect({
        values: [pipelineAccessLogic, ['canEnableNewDestinations'], featureFlagLogic, ['featureFlags']],
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
    loaders(({ props }) => ({
        rawTemplates: [
            [] as HogFunctionTemplateType[],
            {
                loadHogFunctionTemplates: async () => {
                    return (await api.hogFunctions.listTemplates(props.type)).results
                },
            },
        ],
    })),
    selectors({
        loading: [(s) => [s.rawTemplatesLoading], (x) => x],
        templates: [
            (s) => [s.rawTemplates, s.filters],
            (rawTemplates, { subTemplateId }): HogFunctionTemplateType[] => {
                if (!subTemplateId) {
                    return rawTemplates
                }
                const templates: HogFunctionTemplateType[] = []
                // We want to pull out the sub templates and return the template but with overrides applied

                rawTemplates.forEach((template) => {
                    const subTemplate = template.sub_templates?.find((subTemplate) => subTemplate.id === subTemplateId)

                    if (subTemplate) {
                        templates.push({
                            ...template,
                            name: subTemplate.name,
                            description: subTemplate.description ?? template.description,
                        })
                    }
                })

                return templates
            },
        ],
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

        canEnableHogFunction: [
            (s) => [s.canEnableNewDestinations],
            (canEnableNewDestinations): ((template: HogFunctionTemplateType) => boolean) => {
                return (template: HogFunctionTemplateType) => {
                    return template?.status === 'free' || canEnableNewDestinations
                }
            },
        ],

        urlForTemplate: [
            (s) => [s.filters],
            (filters): ((template: HogFunctionTemplateType) => string) => {
                return (template: HogFunctionTemplateType) => {
                    // Add the filters to the url and the template id
                    const subTemplateId = filters.subTemplateId

                    return combineUrl(
                        hogFunctionNewUrl(template.type, template.id),
                        {
                            sub_template: subTemplateId,
                        },
                        {
                            configuration: {
                                filters: filters.filters,
                            },
                        }
                    ).url
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
