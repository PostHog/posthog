import { actions, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { PipelineStage, PluginConfigTypeNew, PluginConfigWithPluginInfoNew, PluginType } from '~/types'

import type { frontendAppsLogicType } from './frontendAppsLogicType'
import { convertToPipelineNode, SiteApp } from './types'
import { capturePluginEvent, checkPermissions, loadPluginsFromUrl } from './utils'

export const frontendAppsLogic = kea<frontendAppsLogicType>([
    path(['scenes', 'pipeline', 'frontendAppsLogic']),
    connect({
        values: [teamLogic, ['currentTeamId'], userLogic, ['user']],
    }),
    actions({
        loadPluginConfigs: true,
        updatePluginConfig: (pluginConfig: PluginConfigTypeNew) => ({ pluginConfig }),
    }),
    loaders(({ values }) => ({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
                    return loadPluginsFromUrl('api/organizations/@current/pipeline_frontend_apps')
                },
            },
        ],
        pluginConfigs: [
            {} as Record<number, PluginConfigTypeNew>,
            {
                loadPluginConfigs: async () => {
                    const res: PluginConfigTypeNew[] = await api.loadPaginatedResults(
                        `api/projects/${values.currentTeamId}/pipeline_frontend_apps_configs`
                    )

                    return Object.fromEntries(res.map((pluginConfig) => [pluginConfig.id, pluginConfig]))
                },
                toggleEnabled: async ({ id, enabled }) => {
                    if (!checkPermissions(PipelineStage.SiteApp, enabled)) {
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
                updatePluginConfig: ({ pluginConfig }) => {
                    return {
                        ...values.pluginConfigs,
                        [pluginConfig.id]: pluginConfig,
                    }
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.pluginsLoading, s.pluginConfigsLoading],
            (pluginsLoading, pluginConfigsLoading) => pluginsLoading || pluginConfigsLoading,
        ],
        frontendApps: [
            (s) => [s.plugins, s.pluginConfigs],
            (plugins, pluginConfigs): SiteApp[] => {
                const rawFrontendApp: PluginConfigWithPluginInfoNew[] = Object.values(
                    pluginConfigs
                ).map<PluginConfigWithPluginInfoNew>((pluginConfig) => ({
                    ...pluginConfig,
                    plugin_info: plugins[pluginConfig.plugin] || null,
                }))
                const convertedFrontendApps = rawFrontendApp.map((t) => convertToPipelineNode(t, PipelineStage.SiteApp))
                const enabledFirst = convertedFrontendApps.sort((a, b) => Number(b.enabled) - Number(a.enabled))
                return enabledFirst
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadPluginConfigs()
    }),
])
