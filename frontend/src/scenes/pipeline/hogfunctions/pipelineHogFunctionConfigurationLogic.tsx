import { kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

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

                    throw new Error('Template not found')
                },

                updateHogFunction: async (data) => {
                    if (!props.id) {
                        return null
                    }

                    throw new Error('Template not found')
                },
            },
        ],
    })),
    // selectors(() => ({
    //     plugin: [
    //         (s) => [s.pluginFromPluginId, s.pluginConfig],
    //         (pluginFromId, pluginConfig) => pluginConfig?.plugin_info || pluginFromId,
    //     ],
    //     pluginConfigSchema: [(s) => [s.plugin], (plugin) => getConfigSchemaArray(plugin?.config_schema || {})],
    //     loading: [
    //         (s) => [s.pluginFromPluginIdLoading, s.pluginConfigLoading],
    //         (pluginLoading, pluginConfigLoading) => pluginLoading || pluginConfigLoading,
    //     ],
    //     savedConfiguration: [
    //         (s) => [s.pluginConfig, s.plugin],
    //         (pluginConfig, plugin) => {
    //             if (!pluginConfig || !plugin) {
    //                 return {}
    //             }
    //             if (pluginConfig) {
    //                 return getConfigurationFromPluginConfig(pluginConfig)
    //             }
    //             if (plugin) {
    //                 return getDefaultConfiguration(plugin)
    //             }
    //         },
    //     ],
    //     requiredFields: [
    //         (s) => [s.plugin, s.configuration],
    //         (plugin, configuration): string[] => {
    //             if (!plugin || !configuration) {
    //                 return []
    //             }
    //             return determineRequiredFields((fieldName) => configuration[fieldName], plugin)
    //         },
    //     ],
    //     hiddenFields: [
    //         (s) => [s.plugin, s.configuration],
    //         (plugin, configuration): string[] => {
    //             if (!plugin || !configuration) {
    //                 return []
    //             }
    //             return determineInvisibleFields((fieldName) => configuration[fieldName], plugin)
    //         },
    //     ],
    //     isNew: [(_, p) => [p.pluginConfigId], (pluginConfigId): boolean => !pluginConfigId],
    //     stage: [(_, p) => [p.stage], (stage) => stage],

    //     pluginFilteringEnabled: [
    //         (s) => [s.featureFlags, s.pluginConfig, s.plugin],
    //         (featureFlags, pluginConfig, plugin): boolean => {
    //             const pluginFilteringEnabled = featureFlags[FEATURE_FLAGS.PLUGINS_FILTERING]
    //             return !!(
    //                 (pluginFilteringEnabled || pluginConfig?.filters) &&
    //                 plugin?.capabilities?.methods?.includes('composeWebhook')
    //             )
    //         },
    //     ],
    // })),
    forms(({ asyncActions, values }) => ({
        hogFunction: {
            defaults: null as HogFunctionType | null,
            errors: (data) => {
                return {}
            },
            submit: async (data) => {
                await asyncActions.updateHogFunction(data)
            },
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
    // afterMount(({ props, actions, cache }) => {
    //     if (props.pluginConfigId) {
    //         actions.loadPluginConfig() // comes with plugin info
    //     } else if (props.pluginId) {
    //         cache.configFromUrl = router.values.hashParams.configuration

    //         actions.loadPlugin()
    //     }
    // }),

    // subscriptions(({ values, actions, cache }) => ({
    //     configuration: (configuration) => {
    //         if (values.isNew) {
    //             // Sync state to the URL bar if new
    //             cache.ignoreUrlChange = true
    //             router.actions.replace(router.values.location.pathname, undefined, {
    //                 configuration,
    //             })
    //         }
    //     },
    //     pluginFromPluginId: (plugin) => {
    //         if (plugin && values.isNew) {
    //             // Sync state from the URL bar if new

    //             // Hash params never hit the server so are relatively safe
    //             if (cache.configFromUrl) {
    //                 actions.resetConfiguration({
    //                     ...values.configuration,
    //                     ...cache.configFromUrl,
    //                 })
    //             }
    //         }
    //     },
    // })),
])
