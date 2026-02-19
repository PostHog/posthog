import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { cleanSourceId, isManagedSourceId, isSelfManagedSourceId } from 'scenes/data-warehouse/utils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    CyclotronJobFiltersType,
    HogFunctionSubTemplateIdType,
    HogFunctionTemplateType,
    HogFunctionTemplateWithSubTemplateType,
    HogFunctionTypeType,
    HogFunctionUserTemplateType,
    UserType,
} from '~/types'

import { getSubTemplate } from '../sub-templates/sub-templates'
import type { hogFunctionTemplateListLogicType } from './hogFunctionTemplateListLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFunctionTemplateType> {}

export type HogFunctionTemplateListFilters = {
    search?: string
}

export type HogFunctionTemplateListLogicProps = {
    /** The primary type of hog function to list */
    type: HogFunctionTypeType
    /** Additional types to list */
    additionalTypes?: HogFunctionTypeType[]
    /** If provided, only those templates will be shown */
    subTemplateIds?: HogFunctionSubTemplateIdType[] | null
    /** Overrides to be used when creating a new hog function */
    getConfigurationOverrides?: (subTemplateId?: HogFunctionSubTemplateIdType) => CyclotronJobFiltersType | undefined
    syncFiltersWithUrl?: boolean
    manualTemplates?: HogFunctionTemplateType[] | null
    manualTemplatesLoading?: boolean
    hideComingSoonByDefault?: boolean
    customFilterFunction?: (template: HogFunctionTemplateType) => boolean
    /** Extra search params to include in the URL when navigating to create a new hog function */
    queryParams?: Record<string, string>
}

export const shouldShowHogFunctionTemplate = (
    hogFunctionTemplate: HogFunctionTemplateType,
    user?: UserType | null
): boolean => {
    if (!user) {
        return false
    }
    if (hogFunctionTemplate.status === 'hidden' && !user.is_staff) {
        return false
    }
    return true
}

export const hogFunctionTemplateListLogic = kea<hogFunctionTemplateListLogicType>([
    props({
        manualTemplates: null,
        subTemplateIds: null,
    } as HogFunctionTemplateListLogicProps),
    key(
        (props) =>
            `${props.syncFiltersWithUrl ? 'scene' : 'default'}/${props.type ?? 'destination'}/${
                props.subTemplateIds?.join(',') ?? ''
            }`
    ),
    path((id) => ['scenes', 'pipeline', 'destinationsLogic', id]),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], userLogic, ['user', 'hasAvailableFeature']],
    })),
    actions({
        setFilters: (filters: Partial<HogFunctionTemplateListFilters>) => ({ filters }),
        resetFilters: true,
        registerInterest: (template: HogFunctionTemplateType) => ({ template }),
        deleteUserTemplate: (id: string) => ({ id }),
    }),
    reducers(() => ({
        filters: [
            {} as HogFunctionTemplateListFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                resetFilters: () => ({}),
            },
        ],
    })),
    loaders(({ props }) => ({
        rawTemplates: [
            [] as HogFunctionTemplateType[],
            {
                loadHogFunctionTemplates: async () => {
                    return (
                        await api.hogFunctions.listTemplates({
                            types: [props.type, ...(props.additionalTypes || [])],
                        })
                    ).results
                },
            },
        ],
        userTemplates: [
            [] as HogFunctionUserTemplateType[],
            {
                loadUserTemplates: async () => {
                    const response = await api.hogFunctionUserTemplates.list()
                    return response.results.filter((t) =>
                        [props.type, ...(props.additionalTypes || [])].includes(t.type as HogFunctionTypeType)
                    )
                },
            },
        ],
    })),
    selectors({
        loading: [(s) => [s.rawTemplatesLoading, s.userTemplatesLoading], (a, b) => a || b],

        userTemplatesAsTemplates: [
            (s) => [s.userTemplates],
            (userTemplates: HogFunctionUserTemplateType[]): HogFunctionTemplateWithSubTemplateType[] => {
                return userTemplates.map((ut) => ({
                    id: `user-template-${ut.id}`,
                    type: ut.type as HogFunctionTypeType,
                    name: ut.name,
                    description: ut.description,
                    icon_url: ut.icon_url ?? undefined,
                    inputs_schema: ut.inputs_schema,
                    filters: ut.filters,
                    mappings: ut.mappings,
                    masking: ut.masking,
                    status: 'stable' as const,
                    free: true,
                    code: ut.hog,
                    code_language: 'hog' as const,
                    user_template_id: ut.id,
                    user_template_scope: ut.scope,
                    tags: ut.tags,
                    created_by: ut.created_by,
                }))
            },
        ],

        systemTemplates: [
            (s) => [
                s.rawTemplates,
                s.user,
                s.featureFlags,
                (_, p: HogFunctionTemplateListLogicProps) => p.manualTemplates ?? [],
                (_, p: HogFunctionTemplateListLogicProps) => p.subTemplateIds ?? [],
            ],
            (
                rawTemplates,
                user,
                featureFlags,
                manualTemplates,
                subTemplateIds
            ): HogFunctionTemplateWithSubTemplateType[] => {
                let templates: HogFunctionTemplateWithSubTemplateType[] = []

                if (!subTemplateIds?.length) {
                    templates = [
                        ...rawTemplates,
                        ...(manualTemplates || []),
                    ] as HogFunctionTemplateWithSubTemplateType[]
                } else {
                    for (const template of rawTemplates) {
                        for (const subTemplateId of subTemplateIds ?? []) {
                            const subTemplate = getSubTemplate(template, subTemplateId)

                            if (subTemplate) {
                                templates.push({
                                    ...template,
                                    ...subTemplate,
                                })
                            }
                        }
                    }
                }

                return templates
                    .filter((x) => shouldShowHogFunctionTemplate(x, user))
                    .filter((x) => !x.flag || !!featureFlags[x.flag as FeatureFlagKey])
                    .filter((x) => x.type !== 'source_webhook' || !!featureFlags[FEATURE_FLAGS.CDP_HOG_SOURCES])
                    .sort((a, b) => (a.name || '').localeCompare(b.name || ''))
            },
        ],

        templates: [
            (s) => [s.systemTemplates, s.userTemplatesAsTemplates],
            (systemTemplates, userTemplatesAsTemplates): HogFunctionTemplateWithSubTemplateType[] => {
                return [...userTemplatesAsTemplates, ...systemTemplates]
            },
        ],

        templatesFuse: [
            (s) => [s.templates],
            (templates): Fuse => {
                return new FuseClass(templates || [], {
                    keys: ['name', 'description'],
                    threshold: 0.3,
                })
            },
        ],

        filteredUserTemplates: [
            (s) => [s.filters, s.userTemplatesAsTemplates, s.templatesFuse],
            (filters, userTemplates, templatesFuse): HogFunctionTemplateType[] => {
                const { search } = filters

                if (search) {
                    return templatesFuse
                        .search(search)
                        .map((x) => x.item)
                        .filter((item) => !!(item as any).user_template_id) as HogFunctionTemplateType[]
                }

                return userTemplates as HogFunctionTemplateType[]
            },
        ],

        filteredTemplates: [
            (s) => [
                s.filters,
                s.systemTemplates,
                s.templatesFuse,
                (_, props) => props.hideComingSoonByDefault ?? false,
                (_, props) => props.customFilterFunction ?? (() => true),
            ],
            (
                filters,
                systemTemplates,
                templatesFuse,
                hideComingSoonByDefault,
                customFilterFunction
            ): HogFunctionTemplateType[] => {
                const { search } = filters

                if (search) {
                    return templatesFuse
                        .search(search)
                        .map((x) => {
                            if (!customFilterFunction(x.item)) {
                                return null
                            }
                            if ((x.item as any).user_template_id) {
                                return null
                            }
                            return x.item
                        })
                        .filter(Boolean) as HogFunctionTemplateType[]
                }

                const [available, comingSoon] = systemTemplates.reduce(
                    ([available, comingSoon], template) => {
                        if (!customFilterFunction(template)) {
                            return [available, comingSoon]
                        }

                        if (template.status === 'coming_soon') {
                            if (!hideComingSoonByDefault) {
                                comingSoon.push(template)
                            }
                        } else {
                            available.push(template)
                        }
                        return [available, comingSoon]
                    },
                    [[], []] as HogFunctionTemplateType[][]
                )

                return [...available, ...comingSoon]
            },
        ],

        urlForTemplate: [
            () => [(_, props) => props],
            ({
                getConfigurationOverrides,
                queryParams,
            }): ((template: HogFunctionTemplateWithSubTemplateType) => string | null) => {
                return (template: HogFunctionTemplateWithSubTemplateType) => {
                    if (template.status === 'coming_soon') {
                        // "Coming soon" sources don't have docs yet
                        if (template.type === 'source') {
                            return null
                        }

                        return `https://posthog.com/docs/cdp/${template.type}s/${template.id}`
                    }

                    // TRICKY: Hacky place but this is where we handle "nonHogFunctionTemplates" to modify the linked url

                    if (isManagedSourceId(template.id) || isSelfManagedSourceId(template.id)) {
                        return urls.dataWarehouseSourceNew(cleanSourceId(template.id))
                    }

                    if (template.id.startsWith('batch-export-')) {
                        return urls.batchExportNew(template.id.replace('batch-export-', ''))
                    }

                    if ((template as any).user_template_id) {
                        return combineUrl(urls.hogFunction('new'), {
                            ...queryParams,
                            userTemplateId: (template as any).user_template_id,
                        }).url
                    }

                    const subTemplate = template.sub_template_id
                        ? getSubTemplate(template, template.sub_template_id)
                        : null

                    const configurationOverrides = getConfigurationOverrides
                        ? getConfigurationOverrides(subTemplate?.sub_template_id)
                        : null

                    const filters =
                        configurationOverrides || subTemplate?.filters
                            ? {
                                  ...subTemplate?.filters,
                                  ...configurationOverrides,
                              }
                            : undefined

                    const configuration: Record<string, any> = {
                        ...subTemplate,
                        ...(filters ? { filters } : {}),
                    }

                    return combineUrl(urls.hogFunctionNew(template.id), queryParams ?? {}, {
                        configuration,
                    }).url
                }
            },
        ],

        editUrlForTemplate: [
            () => [(_, props) => props],
            ({ queryParams }): ((template: HogFunctionTemplateWithSubTemplateType) => string | null) => {
                return (template: HogFunctionTemplateWithSubTemplateType) => {
                    const userTemplateId = (template as any).user_template_id
                    if (!userTemplateId) {
                        return null
                    }
                    return combineUrl(urls.hogFunction('new'), {
                        ...queryParams,
                        editUserTemplateId: userTemplateId,
                    }).url
                }
            },
        ],
    }),

    listeners(({ values, actions }) => ({
        loadHogFunctionTemplates: () => {
            actions.loadUserTemplates()
        },
        registerInterest: ({ template }) => {
            posthog.capture('notify_me_pipeline', {
                name: template.name,
                type: template.type,
                email: values.user?.email,
            })

            lemonToast.success('Thank you for your interest! We will notify you when this feature is available.')
        },
        deleteUserTemplate: async ({ id }) => {
            try {
                await api.hogFunctionUserTemplates.delete(id)
                lemonToast.success('Template deleted')
                actions.loadUserTemplates()
            } catch (e: any) {
                lemonToast.error(e?.detail || e?.message || 'Failed to delete template')
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
