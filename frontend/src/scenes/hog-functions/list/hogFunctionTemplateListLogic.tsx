import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { createFuse } from 'lib/utils/fuseSearch'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    HogFunctionSubTemplateIdType,
    HogFunctionSubTemplateType,
    HogFunctionTemplateType,
    HogFunctionTemplateWithSubTemplateType,
    HogFunctionTypeType,
    UserType,
} from '~/types'

import { cleanSourceId, isManagedSourceId, isSelfManagedSourceId } from 'products/data_warehouse/frontend/utils'

import { HogFunctionDeliveryType, getHogFunctionDeliveryType } from '../hog-function-utils'
import { getSubTemplate } from '../sub-templates/sub-templates'
import type { hogFunctionTemplateListLogicType } from './hogFunctionTemplateListLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFunctionTemplateType> {}

export type HogFunctionTemplateListFilters = {
    search?: string
    deliveryType?: HogFunctionDeliveryType
}

export type HogFunctionTemplateListLogicProps = {
    /** The primary type of hog function to list */
    type: HogFunctionTypeType
    /** Additional types to list */
    additionalTypes?: HogFunctionTypeType[]
    /** If provided, only those templates will be shown */
    subTemplateIds?: HogFunctionSubTemplateIdType[] | null
    /**
     * Overrides to merge into the sub-template before building the new-function URL.
     * Common fields: `filters` (merged with the sub-template's defaults), `name`,
     * `description`. Anything else returned overrides the matching field on the
     * sub-template. The resolved sub-template is passed as the second argument so
     * callers that need to decorate the sub-template's own name/description (e.g.
     * health alerts adding the selected `kind` to the name) can do so.
     */
    getConfigurationOverrides?: (
        subTemplateId: HogFunctionSubTemplateIdType | undefined,
        subTemplate: HogFunctionSubTemplateType | null
    ) => Partial<HogFunctionSubTemplateType> | undefined
    syncFiltersWithUrl?: boolean
    manualTemplates?: HogFunctionTemplateType[] | null
    manualTemplatesLoading?: boolean
    hideComingSoonByDefault?: boolean
    customFilterFunction?: (template: HogFunctionTemplateType) => boolean
    /** Extra search params to include in the URL when navigating to create a new hog function */
    queryParams?: Record<string, string>
}

// Stable references for default prop values - avoids reselect input stability warnings
// caused by `?? []` / `?? () => true` creating new references on every selector call.
const EMPTY_ARRAY: never[] = []
const ALWAYS_TRUE = (): boolean => true

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
    })),
    selectors({
        loading: [(s) => [s.rawTemplatesLoading], (x) => x],

        templates: [
            (s) => [
                s.rawTemplates,
                s.user,
                s.featureFlags,
                (_, p: HogFunctionTemplateListLogicProps) => p.manualTemplates ?? EMPTY_ARRAY,
                (_, p: HogFunctionTemplateListLogicProps) => p.subTemplateIds ?? EMPTY_ARRAY,
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
                    // Special case for listing sub templates - we
                    for (const template of rawTemplates) {
                        for (const subTemplateId of subTemplateIds ?? []) {
                            const subTemplate = getSubTemplate(template, subTemplateId)

                            if (subTemplate) {
                                // Store it with the overrides applied
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
                    .filter(
                        (x) =>
                            x.id !== 'template-source-vercel-log-drain' ||
                            !!featureFlags[FEATURE_FLAGS.CDP_VERCEL_LOG_DRAIN]
                    )
                    .filter((x) => x.id !== 'template-microsoft-ads' || !!featureFlags[FEATURE_FLAGS.CDP_MICROSOFT_ADS])
                    .sort((a, b) => (a.name || '').localeCompare(b.name || ''))
            },
        ],

        templatesFuse: [
            (s) => [s.templates],
            (templates): Fuse => {
                return createFuse(templates || [], {
                    keys: ['name', 'description'],
                })
            },
        ],

        filteredTemplates: [
            (s) => [
                s.filters,
                s.templates,
                s.templatesFuse,
                (_, props) => props.hideComingSoonByDefault ?? false,
                (_, props) => props.customFilterFunction ?? ALWAYS_TRUE,
            ],
            (
                filters,
                templates,
                templatesFuse,
                hideComingSoonByDefault,
                customFilterFunction
            ): HogFunctionTemplateType[] => {
                const { search, deliveryType } = filters
                const matchesDelivery = (template: HogFunctionTemplateType): boolean =>
                    !deliveryType || getHogFunctionDeliveryType(template) === deliveryType

                if (search) {
                    return templatesFuse
                        .search(search)
                        .map((x) => {
                            if (!customFilterFunction(x.item) || !matchesDelivery(x.item)) {
                                return null
                            }
                            return x.item
                        })
                        .filter(Boolean) as HogFunctionTemplateType[]
                }

                const [available, comingSoon] = templates.reduce(
                    ([available, comingSoon], template) => {
                        if (!customFilterFunction(template) || !matchesDelivery(template)) {
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

                    const subTemplate = template.sub_template_id
                        ? getSubTemplate(template, template.sub_template_id)
                        : null

                    const overrides = getConfigurationOverrides
                        ? getConfigurationOverrides(subTemplate?.sub_template_id, subTemplate)
                        : undefined

                    const mergedFilters =
                        overrides?.filters || subTemplate?.filters
                            ? {
                                  ...subTemplate?.filters,
                                  ...overrides?.filters,
                              }
                            : undefined

                    const configuration: Record<string, any> = {
                        ...subTemplate,
                        ...overrides,
                        ...(mergedFilters ? { filters: mergedFilters } : {}),
                    }

                    return combineUrl(urls.hogFunctionNew(template.id), queryParams ?? {}, {
                        configuration,
                    }).url
                }
            },
        ],
    }),

    listeners(({ values }) => ({
        registerInterest: ({ template }) => {
            posthog.capture('notify_me_pipeline', {
                name: template.name,
                type: template.type,
                // Canonical template id (e.g. "managed-<SourceType>" for coming-soon
                // warehouse sources) so consumers can match requests exactly instead
                // of via the free-text display name.
                template_id: template.id,
                email: values.user?.email,
            })

            lemonToast.success('Thank you for your interest! We will notify you when this feature is available.')
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
