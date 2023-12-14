import { actions, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { canConfigurePlugins } from 'scenes/plugins/access'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { PluginConfigTypeNew, PluginType, ProductKey } from '~/types'

import type { pipelineDestinationsLogicType } from './destinationsLogicType'
import { capturePluginEvent } from './utils'

export const pipelineDestinationsLogic = kea<pipelineDestinationsLogicType>([
    path(['scenes', 'pipeline', 'destinationsLogic']),
    connect({
        values: [teamLogic, ['currentTeamId'], userLogic, ['user']],
    }),
    actions({
        loadPluginConfigs: true,
    }),
    loaders(({ values }) => ({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
                    const results: PluginType[] = await api.loadPaginatedResults(
                        `api/organizations/@current/pipeline_destinations`
                    )
                    const plugins: Record<number, PluginType> = {}
                    for (const plugin of results) {
                        plugins[plugin.id] = plugin
                    }
                    return plugins
                },
            },
        ],
        pluginConfigs: [
            {} as Record<number, PluginConfigTypeNew>,
            {
                loadPluginConfigs: async () => {
                    const pluginConfigs: Record<number, PluginConfigTypeNew> = {}
                    const results = await api.loadPaginatedResults(
                        `api/projects/${values.currentTeamId}/pipeline_destinations_configs`
                    )

                    for (const pluginConfig of results) {
                        pluginConfigs[pluginConfig.id] = {
                            ...pluginConfig,
                            // If this pluginConfig doesn't have a name of desciption, use the plugin's
                            // note that this will get saved to the db on certain actions and that's fine
                            name: pluginConfig.name || values.plugins[pluginConfig.plugin]?.name || 'Unknown app',
                            description: pluginConfig.description || values.plugins[pluginConfig.plugin]?.description,
                        }
                    }
                    return pluginConfigs
                },
                toggleEnabled: async ({ id, enabled }) => {
                    if (!values.canConfigurePlugins) {
                        return values.pluginConfigs
                    }
                    const { pluginConfigs, plugins } = values
                    const pluginConfig = pluginConfigs[id]
                    const plugin = plugins[pluginConfig.plugin]
                    capturePluginEvent(`plugin ${enabled ? 'enabled' : 'disabled'}`, plugin, pluginConfig)
                    const response = await api.update(`api/plugin_config/${id}`, {
                        enabled,
                    })
                    return { ...pluginConfigs, [id]: response }
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.pluginsLoading, s.pluginConfigsLoading],
            (pluginsLoading, pluginConfigsLoading) => pluginsLoading || pluginConfigsLoading,
        ],
        enabledPluginConfigs: [
            (s) => [s.pluginConfigs],
            (pluginConfigs) => {
                return Object.values(pluginConfigs).filter((pc) => pc.enabled)
            },
        ],
        disabledPluginConfigs: [
            (s) => [s.pluginConfigs],
            (pluginConfigs) => Object.values(pluginConfigs).filter((pc) => !pc.enabled),
        ],
        // This is currently an organization level setting but might in the future be user level
        // it's better to add the permission checks everywhere now
        canConfigurePlugins: [(s) => [s.user], (user) => canConfigurePlugins(user?.organization)],
        shouldShowProductIntroduction: [
            (s) => [s.user],
            (user): boolean => {
                return !user?.has_seen_product_intro_for?.[ProductKey.PIPELINE_DESTINATIONS]
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadPluginConfigs()
    }),
])
