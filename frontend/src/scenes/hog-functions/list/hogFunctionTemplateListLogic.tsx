import { lemonToast } from '@posthog/lemon-ui'
import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import posthog from 'posthog-js'
import { pipelineAccessLogic } from 'scenes/pipeline/pipelineAccessLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    HogFunctionSubTemplateIdType,
    HogFunctionTemplateType,
    HogFunctionTemplateWithSubTemplateType,
    HogFunctionTypeType,
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
    subTemplateIds?: HogFunctionSubTemplateIdType[]
    /** Overrides to be used when creating a new hog function */
    configurationOverrides?: Pick<HogFunctionTemplateType, 'filters'>
    syncFiltersWithUrl?: boolean
    manualTemplates?: HogFunctionTemplateType[]
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
    props({} as HogFunctionTemplateListLogicProps),
    key(
        (props) =>
            `${props.syncFiltersWithUrl ? 'scene' : 'default'}/${props.type ?? 'destination'}/${
                props.subTemplateIds?.join(',') ?? ''
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
    loaders(({ props, values }) => ({
        rawTemplates: [
            [] as HogFunctionTemplateType[],
            {
                loadHogFunctionTemplates: async () => {
                    const dbTemplates = !!values.featureFlags[FEATURE_FLAGS.GET_HOG_TEMPLATES_FROM_DB]
                    return (
                        await api.hogFunctions.listTemplates({
                            types: [props.type, ...(props.additionalTypes || [])],
                            db_templates: dbTemplates,
                        })
                    ).results
                },
            },
        ],
    })),
    selectors({
        loading: [(s) => [s.rawTemplatesLoading], (x) => x],

        templates: [
            (s) => [s.rawTemplates, (_, props) => props],
            (
                rawTemplates,
                { subTemplateIds, manualTemplates }: HogFunctionTemplateListLogicProps
            ): HogFunctionTemplateWithSubTemplateType[] => {
                if (!subTemplateIds) {
                    return [...rawTemplates, ...(manualTemplates || [])] as HogFunctionTemplateWithSubTemplateType[]
                }

                const final: HogFunctionTemplateWithSubTemplateType[] = []

                // Special case for listing sub templates - we
                for (const template of rawTemplates) {
                    for (const subTemplateId of subTemplateIds ?? []) {
                        const subTemplate = getSubTemplate(template, subTemplateId)

                        if (subTemplate) {
                            // Store it with the overrides applied
                            final.push({
                                ...template,
                                ...subTemplate,
                            })
                        }
                    }
                }

                return final
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
            (s) => [s.filters, s.templates, s.templatesFuse, s.user, s.featureFlags],
            (filters, templates, templatesFuse, user, featureFlags): HogFunctionTemplateType[] => {
                const { search } = filters

                const flagComingSoon = !!featureFlags[FEATURE_FLAGS.SHOW_COMING_SOON_DESTINATIONS]

                return (search ? templatesFuse.search(search).map((x) => x.item) : templates).filter(
                    (x) =>
                        shouldShowHogFunctionTemplate(x, user) &&
                        (x.status === 'coming_soon' ? search && flagComingSoon : true)
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
            () => [(_, props) => props],
            ({ configurationOverrides }): ((template: HogFunctionTemplateWithSubTemplateType) => string) => {
                return (template: HogFunctionTemplateWithSubTemplateType) => {
                    if (template.status === 'coming_soon') {
                        return `https://posthog.com/docs/cdp/${template.type}s/${template.id}`
                    }

                    // TRICKY: Hacky place but this is where we handle "nonHogFunctionTemplates" to modify the linked url

                    if (template.id.startsWith('managed-') || template.id.startsWith('self-managed-')) {
                        return (
                            urls.dataWarehouseSourceNew() +
                            '?kind=' +
                            template.id.replace('self-managed-', '').replace('managed-', '')
                        )
                    }

                    if (template.id.startsWith('batch-export-')) {
                        return urls.batchExportNew(template.id.replace('batch-export-', ''))
                    }

                    const subTemplate = template.sub_template_id
                        ? getSubTemplate(template, template.sub_template_id)
                        : null

                    const configuration: Record<string, any> = {
                        ...(subTemplate ?? {}),
                        ...(configurationOverrides ?? {}),
                    }

                    return combineUrl(
                        urls.hogFunctionNew(template.id),
                        {},
                        {
                            configuration,
                        }
                    ).url
                }
            },
        ],
    }),

    listeners(({ values }) => ({
        registerInterest: ({ template }) => {
            posthog.capture('notify_me_pipeline', {
                name: template.name,
                type: template.type,
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
