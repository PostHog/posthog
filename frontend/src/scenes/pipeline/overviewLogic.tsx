import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { BatchExportConfiguration, PipelineAppKind, PipelineAppTab, PluginConfigTypeNew, PluginType } from '~/types'

import { DestinationType, PipelineAppBackend } from './destinationsLogic'
import type { pipelineOverviewLogicType } from './overviewLogicType'

export const pipelineOverviewLogic = kea<pipelineOverviewLogicType>([
    path(['scenes', 'pipeline', 'overviewLogic']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    loaders(({ values }) => ({
        transformationPlugins: [
            {} as Record<number, PluginType>,
            {
                loadTransformationPlugins: async () => {
                    const results: PluginType[] = await api.loadPaginatedResults(
                        `api/organizations/@current/pipeline_transformations`
                    )
                    const plugins: Record<number, PluginType> = {}
                    for (const plugin of results) {
                        plugins[plugin.id] = plugin
                    }
                    return plugins
                },
            },
        ],
        transformationPluginConfigs: [
            {} as Record<number, PluginConfigTypeNew>,
            {
                loadTransformationPluginConfigs: async () => {
                    const res: PluginConfigTypeNew[] = await api.loadPaginatedResults(
                        `api/projects/${values.currentTeamId}/pipeline_transformation_configs`
                    )

                    return Object.fromEntries(res.map((pluginConfig) => [pluginConfig.id, pluginConfig]))
                },
            },
        ],

        destinationPlugins: [
            {} as Record<number, PluginType>,
            {
                loadDestinationPlugins: async () => {
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
        destinationPluginConfigs: [
            {} as Record<number, PluginConfigTypeNew>,
            {
                loadDestinationPluginConfigs: async () => {
                    const pluginConfigs: Record<number, PluginConfigTypeNew> = {}
                    const results = await api.loadPaginatedResults(
                        `api/projects/${values.currentTeamId}/pipeline_destination_configs`
                    )

                    for (const pluginConfig of results) {
                        pluginConfigs[pluginConfig.id] = {
                            ...pluginConfig,
                            // If this pluginConfig doesn't have a name of desciption, use the plugin's
                            // note that this will get saved to the db on certain actions and that's fine
                            name:
                                pluginConfig.name ||
                                values.transformationPlugins[pluginConfig.plugin]?.name ||
                                values.destinationPlugins[pluginConfig.plugin]?.name ||
                                'Unknown app',
                            description:
                                pluginConfig.description ||
                                values.transformationPlugins[pluginConfig.plugin]?.description ||
                                values.destinationPlugins[pluginConfig.plugin]?.description,
                        }
                    }
                    return pluginConfigs
                },
            },
        ],
        batchExportConfigs: [
            {} as Record<string, BatchExportConfiguration>,
            {
                loadBatchExportConfigs: async () => {
                    const results: BatchExportConfiguration[] = await api.loadPaginatedResults(
                        `api/projects/${values.currentTeamId}/batch_exports`
                    )
                    return Object.fromEntries(results.map((batchExport) => [batchExport.id, batchExport]))
                },
            },
        ],
    })),
    selectors({
        transformationsLoading: [
            (s) => [s.transformationPluginsLoading, s.transformationPluginConfigsLoading],
            (transformationPluginsLoading, transformationPluginConfigsLoading) =>
                transformationPluginsLoading || transformationPluginConfigsLoading,
        ],
        transformations: [
            (s) => [s.transformationPluginConfigs, s.transformationPlugins],
            (transformationPluginConfigs, transformationPlugins): DestinationType[] => {
                const enabledPluginConfigs = Object.values(transformationPluginConfigs)
                    .filter((c) => c.enabled)
                    .sort((a, b) => a.order - b.order)
                const disabledPluginConfigs = Object.values(transformationPluginConfigs)
                    .filter((c) => !c.enabled)
                    .sort((a, b) => a.order - b.order)

                const result = [...enabledPluginConfigs, ...disabledPluginConfigs].map<DestinationType>((c) => ({
                    name: c.name,
                    description: c.description,
                    enabled: c.enabled,
                    config_url: urls.pipelineApp(PipelineAppKind.Transformation, c.id, PipelineAppTab.Configuration),
                    metrics_url: urls.pipelineApp(PipelineAppKind.Transformation, c.id, PipelineAppTab.Metrics),
                    logs_url: urls.pipelineApp(PipelineAppKind.Transformation, c.id, PipelineAppTab.Logs),
                    updated_at: c.updated_at,
                    frequency: 'realtime',

                    backend: PipelineAppBackend.Plugin,
                    id: c.id,
                    plugin: transformationPlugins[c.plugin],
                    app_source_code_url: transformationPlugins[c.plugin].url,
                }))

                return result
            },
        ],

        destinationsLoading: [
            (s) => [s.destinationPluginsLoading, s.destinationPluginConfigsLoading, s.batchExportConfigsLoading],
            (pluginsLoading, destinationPluginConfigsLoading, batchExportConfigsLoading) =>
                pluginsLoading || destinationPluginConfigsLoading || batchExportConfigsLoading,
        ],
        destinations: [
            (s) => [s.destinationPluginConfigs, s.destinationPlugins, s.batchExportConfigs],
            (destinationPluginConfigs, destinationPlugins, batchExportConfigs): DestinationType[] => {
                const appDests = Object.values(destinationPluginConfigs).map<DestinationType>((pluginConfig) => ({
                    name: pluginConfig.name,
                    description: pluginConfig.description,
                    enabled: pluginConfig.enabled,
                    config_url: urls.pipelineApp(
                        PipelineAppKind.Destination,
                        pluginConfig.id,
                        PipelineAppTab.Configuration
                    ),
                    metrics_url: urls.pipelineApp(PipelineAppKind.Destination, pluginConfig.id, PipelineAppTab.Metrics),
                    logs_url: urls.pipelineApp(PipelineAppKind.Destination, pluginConfig.id, PipelineAppTab.Logs),
                    updated_at: pluginConfig.updated_at,
                    frequency: 'realtime',

                    backend: PipelineAppBackend.Plugin,
                    id: pluginConfig.id,
                    plugin: destinationPlugins[pluginConfig.plugin],
                    app_source_code_url: destinationPlugins[pluginConfig.plugin].url,
                }))
                const batchDests = Object.values(batchExportConfigs).map<DestinationType>((batchExport) => ({
                    name: batchExport.name,
                    description: `${batchExport.destination.type} batch export`, // TODO: add to backend
                    enabled: !batchExport.paused,
                    config_url: urls.pipelineApp(
                        PipelineAppKind.Destination,
                        batchExport.id,
                        PipelineAppTab.Configuration
                    ),
                    metrics_url: urls.pipelineApp(PipelineAppKind.Destination, batchExport.id, PipelineAppTab.Metrics),
                    logs_url: urls.pipelineApp(PipelineAppKind.Destination, batchExport.id, PipelineAppTab.Logs),
                    updated_at: batchExport.created_at, // TODO: Add updated_at to batch exports in the backend
                    frequency: batchExport.interval,

                    backend: PipelineAppBackend.BatchExport,
                    id: batchExport.id,
                }))
                const enabledFirst = [...appDests, ...batchDests].sort((a, b) => Number(b.enabled) - Number(a.enabled))
                return enabledFirst
            },
        ],
    }),
    afterMount(({ actions }) => {
        // transformations
        actions.loadTransformationPlugins()
        actions.loadTransformationPluginConfigs()

        // destinations
        actions.loadDestinationPlugins()
        actions.loadDestinationPluginConfigs()
        actions.loadBatchExportConfigs()
    }),
])
