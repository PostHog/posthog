import FuseClass from 'fuse.js'
import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { hogFunctionNewUrl } from 'scenes/pipeline/hogfunctions/urls'
import { pipelineAccessLogic } from 'scenes/pipeline/pipelineAccessLogic'
import { userLogic } from 'scenes/userLogic'

import { HogFunctionSubTemplateIdType, HogFunctionTemplateType, HogFunctionTypeType, UserType } from '~/types'

import type { hogFunctionTemplateListLogicType } from './hogFunctionTemplateListLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFunctionTemplateType> {}

export type HogFunctionTemplateListFilters = {
    search?: string
    filters?: Record<string, any>
}

export type HogFunctionTemplateListLogicProps = {
    type: HogFunctionTypeType
    subTemplateId?: HogFunctionSubTemplateIdType
    defaultFilters?: HogFunctionTemplateListFilters
    forceFilters?: HogFunctionTemplateListFilters
    syncFiltersWithUrl?: boolean
}

export const shouldShowHogFunctionTemplate = (
    hogFunctionTemplate: HogFunctionTemplateType,
    user?: UserType | null
): boolean => {
    if (!user) {
        return false
    }
    if (hogFunctionTemplate.status === 'alpha' && !user.is_staff) {
        return false
    }
    return true
}

const getFunctionFilters = (
    filters: HogFunctionTemplateListFilters,
    template: HogFunctionTemplateType['id']
): Record<string, any> | undefined => {
    if (template.includes('error-tracking-issue-created')) {
        return { events: [{ id: '$error_tracking_issue_created', type: 'events' }] }
    } else if (template.includes('error-tracking-issue-reopened')) {
        return { events: [{ id: '$error_tracking_issue_reopened', type: 'events' }] }
    }
    return filters.filters
}

export const hogFunctionTemplateListLogic = kea<hogFunctionTemplateListLogicType>([
    props({} as HogFunctionTemplateListLogicProps),
    key(
        (props) =>
            `${props.syncFiltersWithUrl ? 'scene' : 'default'}/${props.type ?? 'destination'}/${
                props.subTemplateId ?? ''
            }`
    ),
    path((id) => ['scenes', 'pipeline', 'destinationsLogic', id]),
    connect(() => ({
        values: [
            pipelineAccessLogic,
            ['canEnableNewDestinations'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
        ],
    })),
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
    loaders(({ props, values }) => ({
        templates: [
            [] as HogFunctionTemplateType[],
            {
                loadHogFunctionTemplates: async () => {
                    const dbTemplates = !!values.featureFlags[FEATURE_FLAGS.GET_HOG_TEMPLATES_FROM_DB]
                    return (
                        await api.hogFunctions.listTemplates({
                            types: [props.type],
                            sub_template_id: props.subTemplateId,
                            db_templates: dbTemplates,
                        })
                    ).results
                },
            },
        ],
    })),
    selectors({
        loading: [(s) => [s.templatesLoading], (x) => x],
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
            (s) => [s.filters, s.templates, s.templatesFuse, s.user],
            (filters, templates, templatesFuse, user): HogFunctionTemplateType[] => {
                const { search } = filters
                return (search ? templatesFuse.search(search).map((x) => x.item) : templates).filter((x) =>
                    shouldShowHogFunctionTemplate(x, user)
                )
            },
        ],

        canEnableHogFunction: [
            (s) => [s.canEnableNewDestinations],
            (canEnableNewDestinations): ((template: HogFunctionTemplateType) => boolean) => {
                return (template: HogFunctionTemplateType) => {
                    return template?.free || canEnableNewDestinations
                }
            },
        ],

        urlForTemplate: [
            (s) => [s.filters],
            (filters): ((template: HogFunctionTemplateType) => string) => {
                return (template: HogFunctionTemplateType) => {
                    // Add the filters to the url and the template id
                    return combineUrl(
                        hogFunctionNewUrl(template.type, template.id),
                        {},
                        {
                            configuration: {
                                filters: getFunctionFilters(filters, template.id),
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
