import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { canConfigurePlugins } from 'scenes/plugins/access'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    BatchExportConfiguration,
    BatchExportDestination,
    PipelineAppKind,
    PipelineAppTab,
    PluginConfigTypeNew,
    PluginConfigWithPluginInfoNew,
    PluginType,
    ProductKey,
} from '~/types'

import type { pipelineDestinationsLogicType } from './destinationsLogicType'
import { captureBatchExportEvent, capturePluginEvent } from './utils'

export type DestinationFrequency = 'realtime' | BatchExportConfiguration['interval']

interface DestinationTypeBase {
    name: string
    description?: string
    enabled: boolean
    config_url: string
    metrics_url: string
    logs_url: string
    updated_at: string
    frequency: DestinationFrequency
}

export enum PipelineAppBackend {
    BatchExport = 'batch_export',
    Plugin = 'plugin',
}

interface BatchExportDestinationType extends DestinationTypeBase {
    backend: PipelineAppBackend.BatchExport
    id: string
    data_storage_type: BatchExportDestination['type']
    app_source_code_url?: never
}
export interface WebhookDestination extends DestinationTypeBase {
    backend: PipelineAppBackend.Plugin
    id: number
    plugin: PluginType
    app_source_code_url?: string
}
export type DestinationType = BatchExportDestinationType | WebhookDestination

export const pipelineDestinationsLogic = kea<pipelineDestinationsLogicType>([
    path(['scenes', 'pipeline', 'destinationsLogic']),
    connect({
        values: [teamLogic, ['currentTeamId'], userLogic, ['user']],
    }),
    actions({
        toggleEnabled: (destination: DestinationType, enabled: boolean) => ({ destination, enabled }),
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
                toggleEnabledWebhook: async ({ destination, enabled }) => {
                    if (destination.type === 'batch_export') {
                        return values.pluginConfigs
                    }
                    if (!values.canConfigurePlugins) {
                        return values.pluginConfigs
                    }
                    const { pluginConfigs, plugins } = values
                    const pluginConfig = pluginConfigs[destination.id]
                    const plugin = plugins[pluginConfig.plugin]
                    capturePluginEvent(`plugin ${enabled ? 'enabled' : 'disabled'}`, plugin, pluginConfig)
                    const response = await api.update(`api/plugin_config/${destination.id}`, {
                        enabled,
                    })
                    return { ...pluginConfigs, [destination.id]: response }
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
                toggleEnabledBatchExport: async ({ destination, enabled }) => {
                    const batchExport = values.batchExportConfigs[destination.id]
                    if (enabled) {
                        await api.batchExports.pause(destination.id)
                    } else {
                        await api.batchExports.unpause(destination.id)
                    }
                    captureBatchExportEvent(`batch export ${enabled ? 'enabled' : 'disabled'}`, batchExport)
                    return { ...values.batchExportConfigs, [destination.id]: { ...batchExport, paused: !enabled } }
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.pluginsLoading, s.pluginConfigsLoading, s.batchExportConfigsLoading],
            (pluginsLoading, pluginConfigsLoading, batchExportConfigsLoading) =>
                pluginsLoading || pluginConfigsLoading || batchExportConfigsLoading,
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
        displayablePluginConfigs: [
            (s) => [s.pluginConfigs, s.plugins],
            (pluginConfigs, plugins) => {
                const enabledFirst = Object.values(pluginConfigs).sort((a, b) => Number(b.enabled) - Number(a.enabled))
                const withPluginInfo = enabledFirst.map<PluginConfigWithPluginInfoNew>((pluginConfig) => ({
                    ...pluginConfig,
                    plugin_info: plugins[pluginConfig.plugin] || null,
                }))
                return withPluginInfo
            },
        ],
        destinations: [
            (s) => [s.pluginConfigs, s.plugins, s.batchExportConfigs],
            (pluginConfigs, plugins, batchExportConfigs): DestinationType[] => {
                const appDests = Object.values(pluginConfigs).map<DestinationType>((pluginConfig) => ({
                    backend: PipelineAppBackend.Plugin,
                    frequency: 'realtime',
                    id: pluginConfig.id,
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
                    app_source_code_url: '',
                    plugin: plugins[pluginConfig.plugin],
                    updated_at: pluginConfig.updated_at,
                }))
                const batchDests = Object.values(batchExportConfigs).map<DestinationType>((batchExport) => ({
                    backend: PipelineAppBackend.BatchExport,
                    frequency: batchExport.interval,
                    id: batchExport.id,
                    name: batchExport.name,
                    description: `${batchExport.destination.type} batch export`, // TODO: add to backend
                    data_storage_type: batchExport.destination.type,
                    enabled: !batchExport.paused,
                    config_url: urls.pipelineApp(
                        PipelineAppKind.Destination,
                        batchExport.id,
                        PipelineAppTab.Configuration
                    ),
                    metrics_url: urls.pipelineApp(PipelineAppKind.Destination, batchExport.id, PipelineAppTab.Metrics),
                    logs_url: urls.pipelineApp(PipelineAppKind.Destination, batchExport.id, PipelineAppTab.Logs),
                    updated_at: batchExport.created_at, // TODO: Add updated_at to batch exports in the backend
                }))
                const enabledFirst = [...appDests, ...batchDests].sort((a, b) => Number(b.enabled) - Number(a.enabled))
                return enabledFirst
            },
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
    listeners(({ actions, values }) => ({
        toggleEnabled: async ({ destination, enabled }) => {
            if (!values.canConfigurePlugins) {
                lemonToast.error("You don't have permission to enable or disable destinations")
                return
            }
            if (destination.backend === 'plugin') {
                actions.toggleEnabledWebhook({ destination: destination, enabled: enabled })
            } else {
                actions.toggleEnabledBatchExport({ destination: destination, enabled: enabled })
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadPluginConfigs()
        actions.loadBatchExports()
    }),
])
