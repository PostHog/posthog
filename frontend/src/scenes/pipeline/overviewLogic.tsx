import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { BatchExportConfiguration, PipelineAppTabs, PipelineTabs, PluginConfigTypeNew, PluginType } from '~/types'

import { DestinationType, DestinationTypeKind } from './destinationsLogic'
import type { pipelineOverviewLogicType } from './overviewLogicType'

export const pipelineOverviewLogic = kea<pipelineOverviewLogicType>([
    path(['scenes', 'pipeline', 'overviewLogic']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    loaders(({ values }) => ({
        transformations: [
            [] as PluginType[],
            {
                loadTransformations: async () => {
                    const results: PluginType[] = await api.loadPaginatedResults(
                        `api/organizations/@current/pipeline_transformations`
                    )
                    const plugins: Record<number, PluginType> = {}
                    for (const plugin of results) {
                        plugins[plugin.id] = plugin
                    }
                    return Object.values(plugins)
                },
            },
        ],

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
                        `api/projects/${values.currentTeamId}/pipeline_destination_configs`
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
            },
        ],
        batchExportConfigs: [
            {} as Record<string, BatchExportConfiguration>,
            {
                loadBatchExports: async () => {
                    const results: BatchExportConfiguration[] = await api.loadPaginatedResults(
                        `api/projects/${values.currentTeamId}/batch_exports`
                    )
                    return Object.fromEntries(results.map((batchExport) => [batchExport.id, batchExport]))
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.pluginsLoading, s.pluginConfigsLoading, s.batchExportConfigsLoading, s.transformationsLoading],
            (pluginsLoading, pluginConfigsLoading, batchExportConfigsLoading, transformationsLoading) =>
                pluginsLoading || pluginConfigsLoading || batchExportConfigsLoading || transformationsLoading,
        ],
        destinations: [
            (s) => [s.pluginConfigs, s.plugins, s.batchExportConfigs],
            (pluginConfigs, plugins, batchExportConfigs): DestinationType[] => {
                const appDests = Object.values(pluginConfigs).map<DestinationType>((pluginConfig) => ({
                    type: DestinationTypeKind.Webhook,
                    frequency: 'realtime',
                    id: pluginConfig.id,
                    name: pluginConfig.name,
                    description: pluginConfig.description,
                    enabled: pluginConfig.enabled,
                    config_url: urls.pipelineApp(
                        PipelineTabs.Destinations,
                        pluginConfig.id,
                        PipelineAppTabs.Configuration
                    ),
                    metrics_url: urls.pipelineApp(PipelineTabs.Destinations, pluginConfig.id, PipelineAppTabs.Metrics),
                    logs_url: urls.pipelineApp(PipelineTabs.Destinations, pluginConfig.id, PipelineAppTabs.Logs),
                    app_source_code_url: '',
                    plugin: plugins[pluginConfig.plugin],
                    success_rates: {
                        '24h': pluginConfig.delivery_rate_24h === undefined ? null : pluginConfig.delivery_rate_24h,
                        '7d': null, // TODO: start populating real data for this
                    },
                    updated_at: pluginConfig.updated_at,
                }))
                const batchDests = Object.values(batchExportConfigs).map<DestinationType>((batchExport) => ({
                    type: DestinationTypeKind.BatchExport,
                    frequency: batchExport.interval,
                    id: batchExport.id,
                    name: batchExport.name,
                    description: `${batchExport.destination.type} batch export`, // TODO: add to backend
                    enabled: !batchExport.paused,
                    config_url: urls.pipelineApp(
                        PipelineTabs.Destinations,
                        batchExport.id,
                        PipelineAppTabs.Configuration
                    ),
                    metrics_url: urls.pipelineApp(PipelineTabs.Destinations, batchExport.id, PipelineAppTabs.Metrics),
                    logs_url: urls.pipelineApp(PipelineTabs.Destinations, batchExport.id, PipelineAppTabs.Logs),
                    success_rates: {
                        '24h': [5, 17],
                        '7d': [12, 100043],
                    },
                    updated_at: batchExport.created_at, // TODO: Add updated_at to batch exports in the backend
                }))
                const enabledFirst = [...appDests, ...batchDests].sort((a, b) => Number(b.enabled) - Number(a.enabled))
                return enabledFirst
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadTransformations()
        actions.loadPlugins()
        actions.loadPluginConfigs()
        actions.loadBatchExports()
    }),
])
