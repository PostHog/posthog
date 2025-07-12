import { lemonToast } from '@posthog/lemon-ui'
import { afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
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
    getPluginConfigFormData,
} from './configUtils'
import { DESTINATION_TYPES, SITE_APP_TYPES } from './destinations/constants'
import { pipelineDestinationsLogic } from './destinations/destinationsLogic'
import { frontendAppsLogic } from './frontendAppsLogic'
import { importAppsLogic } from './importAppsLogic'
import { pipelineAccessLogic } from './pipelineAccessLogic'
import type { pipelinePluginConfigurationLogicType } from './pipelinePluginConfigurationLogicType'
import { pipelineTransformationsLogic } from './transformationsLogic'
import { loadPluginsFromUrl } from './utils'

export interface PipelinePluginConfigurationLogicProps {
    stage: PipelineStage | null
    pluginId: number | null
    pluginConfigId: number | null
}

function getConfigurationFromPluginConfig(pluginConfig: PluginConfigWithPluginInfoNew): Record<string, any> {
    return {
        ...pluginConfig.config,
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
            ['plugins as transformationPlugins', 'nextAvailableOrder'],
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

                    let plugins: Record<number, PluginType> = {}

                    // TRICKY: We load from the list as the permissions are a not quite right for getting one.
                    // As we are moving away from plugins opting for this quick fix for now.
                    if (props.stage === PipelineStage.Transformation) {
                        plugins = await loadPluginsFromUrl('api/organizations/@current/pipeline_transformations')
                    } else if (props.stage === PipelineStage.Destination) {
                        plugins = await loadPluginsFromUrl('api/organizations/@current/pipeline_destinations')
                    }

                    return plugins[props.pluginId] || api.get(`api/organizations/@current/plugins/${props.pluginId}`)
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
                    const { enabled, order, name, description, ...config } = formdata

                    const formData = getPluginConfigFormData(
                        values.plugin.config_schema,
                        defaultConfigForPlugin(values.plugin),
                        config
                    )
                    formData.append('enabled', enabled)
                    formData.append('name', name)
                    formData.append('description', description)

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

                migrateToHogFunction: async () => {
                    if (!props.pluginConfigId) {
                        return null
                    }
                    const hogFunction = await api.pluginConfigs.migrate(props.pluginConfigId)

                    router.actions.replace(urls.pipelineNode(PipelineStage.Destination, `hog-${hogFunction.id}`))

                    return values.pluginConfig
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
                pipelineDestinationsLogic
                    .findMounted({ types: DESTINATION_TYPES })
                    ?.actions.updatePluginConfig(pluginConfig)
            } else if (props.stage === PipelineStage.SiteApp) {
                const siteAppsEnabled = !!values.featureFlags[FEATURE_FLAGS.SITE_APP_FUNCTIONS]
                if (siteAppsEnabled) {
                    pipelineDestinationsLogic
                        .findMounted({ types: SITE_APP_TYPES })
                        ?.actions.updatePluginConfig(pluginConfig)
                } else {
                    frontendAppsLogic.findMounted()?.actions.updatePluginConfig(pluginConfig)
                }
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
                    return getDefaultConfiguration(pluginFromPluginId)
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
    })),
    forms(({ asyncActions, values }) => ({
        configuration: {
            errors: (formdata) => {
                return Object.fromEntries(
                    values.requiredFields.map((field) => [
                        field,
                        formdata[field] ? undefined : 'This field is required',
                    ])
                )
            },
            submit: async (formdata) => {
                await asyncActions.updatePluginConfig(formdata)
            },
        },
    })),
    beforeUnload(({ actions, values }) => ({
        enabled: () => values.configurationChanged,
        message: 'Leave action?\nChanges you made will be discarded.',
        onConfirm: () => {
            actions.resetConfiguration()
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.pluginConfigId) {
            actions.loadPluginConfig() // comes with plugin info
        } else if (props.pluginId) {
            actions.loadPlugin()
        }
    }),
])
