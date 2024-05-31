import { lemonToast } from '@posthog/lemon-ui'
import { afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage, PluginConfigWithPluginInfoNew, PluginType } from '~/types'

import {
    defaultConfigForPlugin,
    determineInvisibleFields,
    determineRequiredFields,
    getConfigSchemaArray,
    getPluginConfigFormData,
    sanitizeFilters,
} from './configUtils'
import { pipelineDestinationsLogic } from './destinationsLogic'
import { frontendAppsLogic } from './frontendAppsLogic'
import { importAppsLogic } from './importAppsLogic'
import { pipelineAccessLogic } from './pipelineAccessLogic'
import type { pipelinePluginConfigurationLogicType } from './pipelinePluginConfigurationLogicType'
import { pipelineTransformationsLogic } from './transformationsLogic'

export interface PipelinePluginConfigurationLogicProps {
    stage: PipelineStage | null
    pluginId: number | null
    pluginConfigId: number | null
}

function getConfigurationFromPluginConfig(pluginConfig: PluginConfigWithPluginInfoNew): Record<string, any> {
    return {
        ...pluginConfig.config,
        filters: pluginConfig.filters,
        enabled: pluginConfig.enabled,
        order: pluginConfig.order,
        name: pluginConfig.name ? pluginConfig.name : pluginConfig.plugin_info.name,
        description: pluginConfig.description ? pluginConfig.description : pluginConfig.plugin_info.description || '',
    }
}

function getDefaultConfiguration(plugin: PluginType): Record<string, any> {
    return {
        ...defaultConfigForPlugin(plugin),
        enabled: false,
        name: plugin.name,
        description: plugin.description,
    }
}

// Should likely be somewhat similar to pipelineBatchExportConfigurationLogic
export const pipelinePluginConfigurationLogic = kea<pipelinePluginConfigurationLogicType>([
    props({} as PipelinePluginConfigurationLogicProps),
    key(({ pluginId, pluginConfigId }: PipelinePluginConfigurationLogicProps) => {
        if (pluginConfigId) {
            return `ID:${pluginConfigId}`
        }
        return `NEW:${pluginId}`
    }),
    path((id) => ['scenes', 'pipeline', 'pipelinePluginConfigurationLogic', id]),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            pipelineTransformationsLogic,
            ['nextAvailableOrder'],
            featureFlagLogic,
            ['featureFlags'],
            pipelineAccessLogic,
            ['canEnableNewDestinations'],
        ],
    })),
    loaders(({ props, values }) => ({
        pluginFromPluginId: [
            null as PluginType | null,
            {
                loadPlugin: async () => {
                    if (!props.pluginId) {
                        return null
                    }
                    return await api.get(`api/organizations/@current/plugins/${props.pluginId}`)
                },
            },
        ],
        pluginConfig: [
            null as PluginConfigWithPluginInfoNew | null,
            {
                loadPluginConfig: async () => {
                    if (props.pluginConfigId) {
                        return await api.pluginConfigs.get(props.pluginConfigId)
                    }
                    return null
                },
                updatePluginConfig: async (formdata: Record<string, any>) => {
                    if (!values.plugin || !props.stage) {
                        return null
                    }
                    if (
                        (!values.pluginConfig || (!values.pluginConfig.enabled && formdata.enabled)) &&
                        props.stage === PipelineStage.Destination &&
                        !values.canEnableNewDestinations
                    ) {
                        lemonToast.error('Data pipelines add-on is required for enabling new destinations.')
                        return values.pluginConfig
                    }
                    const { enabled, order, name, description, filters, ...config } = formdata

                    const formData = getPluginConfigFormData(
                        values.plugin.config_schema,
                        defaultConfigForPlugin(values.plugin),
                        config
                    )
                    formData.append('enabled', enabled)
                    formData.append('name', name)
                    if (description) {
                        formData.append('description', description)
                    }

                    const sanitizedFilters = sanitizeFilters(filters)
                    if (filters) {
                        formData.append('filters', sanitizedFilters ? JSON.stringify(sanitizedFilters) : '')
                    }

                    // if enabling a transformation we need to set the order to be last
                    // if already enabled we don't want to change the order
                    // it doesn't matter for other stages so we can use any value
                    const orderFixed =
                        enabled && values.pluginConfig && !values.pluginConfig.enabled
                            ? values.nextAvailableOrder
                            : order || 0
                    formData.append('order', orderFixed)
                    if (props.pluginConfigId) {
                        return await api.pluginConfigs.update(props.pluginConfigId, formData)
                    }
                    formData.append('plugin', values.plugin.id.toString())
                    const res = await api.pluginConfigs.create(formData)
                    router.actions.replace(urls.pipelineNode(props.stage, res.id, PipelineNodeTab.Configuration))
                    return res
                },
            },
        ],
    })),
    listeners(({ props, actions, values }) => ({
        updatePluginConfigSuccess: ({ pluginConfig }) => {
            if (!pluginConfig) {
                return
            }

            // Reset the form so that it doesn't think there are unsaved changes
            actions.resetConfiguration(values.configuration)

            // Navigating back to the list views gets the updated plugin info without refreshing
            if (props.stage === PipelineStage.Transformation) {
                pipelineTransformationsLogic.findMounted()?.actions.updatePluginConfig(pluginConfig)
            } else if (props.stage === PipelineStage.Destination) {
                pipelineDestinationsLogic.findMounted()?.actions.updatePluginConfig(pluginConfig)
            } else if (props.stage === PipelineStage.SiteApp) {
                frontendAppsLogic.findMounted()?.actions.updatePluginConfig(pluginConfig)
            } else if (props.stage === PipelineStage.ImportApp) {
                importAppsLogic.findMounted()?.actions.updatePluginConfig(pluginConfig)
            }
        },
    })),
    reducers(() => ({
        configuration: [
            {} as Record<string, any>,
            {
                loadPluginSuccess: (state, { pluginFromPluginId }) => {
                    // For new pluginConfig creation, we need to set the default values
                    // But if we've already have something better in state, skip this

                    if (Object.keys(state).length > 0 || !pluginFromPluginId) {
                        return state
                    }
                    const config = getDefaultConfiguration(pluginFromPluginId)

                    return config
                },
                loadPluginConfigSuccess: (state, { pluginConfig }) => {
                    if (!pluginConfig) {
                        return state
                    }
                    return getConfigurationFromPluginConfig(pluginConfig)
                },
                updatePluginConfigSuccess: (state, { pluginConfig }) => {
                    if (!pluginConfig) {
                        return state
                    }
                    return getConfigurationFromPluginConfig(pluginConfig)
                },
            },
        ],
    })),
    selectors(() => ({
        plugin: [
            (s) => [s.pluginFromPluginId, s.pluginConfig],
            (pluginFromId, pluginConfig) => pluginConfig?.plugin_info || pluginFromId,
        ],
        pluginConfigSchema: [(s) => [s.plugin], (plugin) => getConfigSchemaArray(plugin?.config_schema || {})],
        loading: [
            (s) => [s.pluginFromPluginIdLoading, s.pluginConfigLoading],
            (pluginLoading, pluginConfigLoading) => pluginLoading || pluginConfigLoading,
        ],
        savedConfiguration: [
            (s) => [s.pluginConfig, s.plugin],
            (pluginConfig, plugin) => {
                if (!pluginConfig || !plugin) {
                    return {}
                }
                if (pluginConfig) {
                    return getConfigurationFromPluginConfig(pluginConfig)
                }
                if (plugin) {
                    return getDefaultConfiguration(plugin)
                }
            },
        ],
        requiredFields: [
            (s) => [s.plugin, s.configuration],
            (plugin, configuration): string[] => {
                if (!plugin || !configuration) {
                    return []
                }
                return determineRequiredFields((fieldName) => configuration[fieldName], plugin)
            },
        ],
        hiddenFields: [
            (s) => [s.plugin, s.configuration],
            (plugin, configuration): string[] => {
                if (!plugin || !configuration) {
                    return []
                }
                return determineInvisibleFields((fieldName) => configuration[fieldName], plugin)
            },
        ],
        isNew: [(_, p) => [p.pluginConfigId], (pluginConfigId): boolean => !pluginConfigId],
        stage: [(_, p) => [p.stage], (stage) => stage],

        filteringEnabled: [
            (s) => [s.featureFlags, s.pluginConfig, s.plugin],
            (featureFlags, pluginConfig, plugin): boolean => {
                const filteringEnabled = featureFlags[FEATURE_FLAGS.PLUGINS_FILTERING]
                return !!(
                    (filteringEnabled || pluginConfig?.filters) &&
                    plugin?.capabilities?.methods?.includes('composeWebhook')
                )
            },
        ],
    })),
    forms(({ asyncActions, values }) => ({
        configuration: {
            errors: (formdata) => {
                const errors = {}

                for (const field of values.pluginConfigSchema ?? []) {
                    if (!field.key) {
                        continue
                    }
                    if (field.required && !formdata[field.key]) {
                        errors[field.key] = 'This field is required'
                    } else if (field.type === 'json') {
                        try {
                            JSON.parse(formdata[field.key])
                        } catch (e) {
                            errors[field.key] = 'Invalid JSON'
                        }
                    }
                }

                return errors
            },
            submit: async (formdata) => {
                await asyncActions.updatePluginConfig(formdata)
            },
        },
    })),
    // TODO: Add this back in once we have a plan for handling automatic url changes
    beforeUnload(({ actions, values, cache }) => ({
        enabled: () => {
            if (cache.ignoreUrlChange) {
                cache.ignoreUrlChange = false
                return false
            }
            return values.configurationChanged
        },
        message: 'Leave action?\nChanges you made will be discarded.',
        onConfirm: () => {
            actions.resetConfiguration()
        },
    })),
    afterMount(({ props, actions, cache }) => {
        if (props.pluginConfigId) {
            actions.loadPluginConfig() // comes with plugin info
        } else if (props.pluginId) {
            cache.configFromUrl = router.values.hashParams.configuration

            actions.loadPlugin()
        }
    }),

    subscriptions(({ values, actions, cache }) => ({
        configuration: (configuration) => {
            if (values.isNew) {
                // Sync state to the URL bar if new
                cache.ignoreUrlChange = true
                router.actions.replace(router.values.location.pathname, undefined, {
                    configuration,
                })
            }
        },
        pluginFromPluginId: (plugin) => {
            if (plugin && values.isNew) {
                // Sync state from the URL bar if new

                // Hash params never hit the server so are relatively safe
                if (cache.configFromUrl) {
                    actions.resetConfiguration({
                        ...values.configuration,
                        ...cache.configFromUrl,
                    })
                }
            }
        },
    })),
])
