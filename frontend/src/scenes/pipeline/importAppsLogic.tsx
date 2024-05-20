import { actions, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { PipelineStage, PluginConfigTypeNew, PluginConfigWithPluginInfoNew, PluginType } from '~/types'

import type { importAppsLogicType } from './importAppsLogicType'
import { convertToPipelineNode, ImportApp } from './types'
import { capturePluginEvent, checkPermissions, loadPluginsFromUrl } from './utils'

export const importAppsLogic = kea<importAppsLogicType>([
    path(['scenes', 'pipeline', 'importAppsLogic']),
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
                    return loadPluginsFromUrl('api/organizations/@current/pipeline_import_apps')
                },
            },
        ],
        pluginConfigs: [
            {} as Record<number, PluginConfigTypeNew>,
            {
                loadPluginConfigs: async () => {
                    const res: PluginConfigTypeNew[] = await api.loadPaginatedResults(
                        `api/projects/${values.currentTeamId}/pipeline_import_apps_configs`
                    )

                    return Object.fromEntries(res.map((pluginConfig) => [pluginConfig.id, pluginConfig]))
                },
                toggleEnabled: async ({ id, enabled }) => {
                    if (!checkPermissions(PipelineStage.ImportApp, enabled)) {
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
        importApps: [
            (s) => [s.plugins, s.pluginConfigs],
            (plugins, pluginConfigs): ImportApp[] => {
                const rawImportApp: PluginConfigWithPluginInfoNew[] = Object.values(
                    pluginConfigs
                ).map<PluginConfigWithPluginInfoNew>((pluginConfig) => ({
                    ...pluginConfig,
                    plugin_info: plugins[pluginConfig.plugin] || null,
                }))
                const convertedImportApps = rawImportApp.map((t) => convertToPipelineNode(t, PipelineStage.ImportApp))
                const enabledFirst = convertedImportApps.sort((a, b) => Number(b.enabled) - Number(a.enabled))
                return enabledFirst
            },
        ],
        hasEnabledImportApps: [(s) => [s.importApps], (importApps) => importApps.some((app) => app.enabled)],
    }),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadPluginConfigs()
    }),
])
