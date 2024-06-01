import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'

import { FilterType, HogFunctionTemplateType, HogFunctionType, PluginConfigFilters, PluginConfigTypeNew } from '~/types'

import type { pipelineHogFunctionConfigurationLogicType } from './pipelineHogFunctionConfigurationLogicType'
import { HOG_FUNCTION_TEMPLATES } from './templates/hog-templates'

export interface PipelineHogFunctionConfigurationLogicProps {
    templateId?: string
    id?: string
}

function sanitizeFilters(filters?: FilterType): PluginConfigTypeNew['filters'] {
    if (!filters) {
        return null
    }
    const sanitized: PluginConfigFilters = {}

    if (filters.events) {
        sanitized.events = filters.events.map((f) => ({
            id: f.id,
            type: 'events',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    if (filters.actions) {
        sanitized.actions = filters.actions.map((f) => ({
            id: f.id,
            type: 'actions',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    if (filters.filter_test_accounts) {
        sanitized.filter_test_accounts = filters.filter_test_accounts
    }

    return Object.keys(sanitized).length > 0 ? sanitized : undefined
}

// Should likely be somewhat similar to pipelineBatchExportConfigurationLogic
export const pipelineHogFunctionConfigurationLogic = kea<pipelineHogFunctionConfigurationLogicType>([
    props({} as PipelineHogFunctionConfigurationLogicProps),
    key(({ id, templateId }: PipelineHogFunctionConfigurationLogicProps) => {
        return id ?? templateId ?? 'new'
    }),
    path((id) => ['scenes', 'pipeline', 'pipelineHogFunctionConfigurationLogic', id]),
    actions({
        clearChanges: true,
        upsertHogFunction: (data: HogFunctionType) => ({ data }),
        setShowSource: (showSource: boolean) => ({ showSource }),
    }),
    // connect(() => ({
    //     values: [
    //         teamLogic,
    //         ['currentTeamId'],
    //         pipelineTransformationsLogic,
    //         ['nextAvailableOrder'],
    //         featureFlagLogic,
    //         ['featureFlags'],
    //         pipelineAccessLogic,
    //         ['canEnableNewDestinations'],
    //     ],
    // })),

    reducers({
        showSource: [
            true,
            {
                setShowSource: (_, { showSource }) => showSource,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        template: [
            null as HogFunctionTemplateType | null,
            {
                loadTemplate: async () => {
                    if (!props.templateId) {
                        return null
                    }
                    const res = HOG_FUNCTION_TEMPLATES.find((template) => template.id === props.templateId)

                    if (!res) {
                        throw new Error('Template not found')
                    }
                    return res
                },
            },
        ],

        hogFunction: [
            null as HogFunctionType | null,
            {
                loadHogFunction: async () => {
                    if (!props.id) {
                        return null
                    }

                    return await api.hogFunctions.get(props.id)
                },

                upsertHogFunction: async ({ data }) => {
                    const payload = {
                        ...data,
                        filters: data.filters ? sanitizeFilters(data.filters) : null,
                    }

                    if (!props.id) {
                        return await api.hogFunctions.create(payload)
                    }
                    return await api.hogFunctions.update(props.id, payload)
                },
            },
        ],
    })),
    selectors(() => ({
        loading: [
            (s) => [s.hogFunctionLoading, s.templateLoading],
            (hogFunctionLoading, templateLoading) => hogFunctionLoading || templateLoading,
        ],
        missing: [
            (s) => [s.loading, s.hogFunction, s.template],
            (loading, hogFunction, template) => !loading && !hogFunction && !template,
        ],
    })),
    forms(({ asyncActions, values }) => ({
        configuration: {
            defaults: {} as HogFunctionType,
            errors: (data) => {
                return {
                    name: !data.name ? 'Name is required' : null,
                }
            },
            submit: async (data) => {
                await asyncActions.upsertHogFunction(data)
            },
        },
    })),

    listeners(({ actions, values, cache }) => ({
        loadTemplateSuccess: ({ template }) => {
            if (template) {
                console.log('RESETTING FORM', template, cache.configFromUrl)
                const form: HogFunctionType = {
                    inputs: {},
                    ...template,
                    ...(cache.configFromUrl || {}),
                }
                actions.resetConfiguration(form)
            }
        },
        clearChanges: () => {
            actions.resetConfiguration(values.hogFunction ?? (values.template as HogFunctionType))
        },
    })),
    // // TODO: Add this back in once we have a plan for handling automatic url changes
    // beforeUnload(({ actions, values, cache }) => ({
    //     enabled: () => {
    //         if (cache.ignoreUrlChange) {
    //             cache.ignoreUrlChange = false
    //             return false
    //         }
    //         return values.configurationChanged
    //     },
    //     message: 'Leave action?\nChanges you made will be discarded.',
    //     onConfirm: () => {
    //         actions.resetConfiguration()
    //     },
    // })),
    afterMount(({ props, actions, cache }) => {
        if (props.templateId) {
            cache.configFromUrl = router.values.hashParams.configuration
            actions.loadTemplate() // comes with plugin info
        } else if (props.id) {
            actions.loadHogFunction()
        }
    }),

    subscriptions(({ props, values, actions, cache }) => ({
        configuration: (configuration) => {
            if (props.templateId) {
                // Sync state to the URL bar if new
                cache.ignoreUrlChange = true
                router.actions.replace(router.values.location.pathname, undefined, {
                    configuration,
                })

                console.log(configuration)
            }
        },
    })),
])
