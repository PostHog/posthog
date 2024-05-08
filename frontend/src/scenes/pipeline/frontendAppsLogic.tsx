import { actions, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { PipelineStage, PluginConfigTypeNew, PluginConfigWithPluginInfoNew, PluginType, ProductKey } from '~/types'

import type { frontendAppsLogicType } from './frontendAppsLogicType'
import { pipelineLogic } from './pipelineLogic'
import { convertToPipelineNode, SiteApp } from './types'
import { loadPluginsFromUrl, patchPluginConfig } from './utils'

export const frontendAppsLogic = kea<frontendAppsLogicType>([
    path(['scenes', 'pipeline', 'frontendAppsLogic']),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user'],
            pipelineLogic,
            ['notAllowedReasonByStageAndOperationType'],
        ],
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
                    const { pluginConfigs, plugins } = values
                    const pluginConfig = pluginConfigs[id]
                    const plugin = plugins[pluginConfig.plugin]
                    const response = await patchPluginConfig(
                        values.notAllowedReasonByOperationType,
                        pluginConfig,
                        plugin,
                        { enabled }
                    )
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
        notAllowedReasonByOperationType: [
            (s) => [s.notAllowedReasonByStageAndOperationType],
            (notAllowedReasonByStageAndOperationType) => notAllowedReasonByStageAndOperationType[PipelineStage.SiteApp],
        ],
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
        shouldShowProductIntroduction: [
            (s) => [s.user],
            (user): boolean => {
                return !user?.has_seen_product_intro_for?.[ProductKey.SITE_APPS]
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadPluginConfigs()
    }),
])
