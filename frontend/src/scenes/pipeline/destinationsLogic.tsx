import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    BatchExportConfiguration,
    HogFunctionTemplateType,
    PipelineStage,
    PluginConfigTypeNew,
    PluginConfigWithPluginInfoNew,
    PluginType,
    ProductKey,
} from '~/types'

import type { pipelineDestinationsLogicType } from './destinationsLogicType'
import { HOG_FUNCTION_TEMPLATES } from './hogfunctions/templates/hog-templates'
import { pipelineAccessLogic } from './pipelineAccessLogic'
import { BatchExportDestination, convertToPipelineNode, Destination, PipelineBackend } from './types'
import { captureBatchExportEvent, capturePluginEvent, loadPluginsFromUrl } from './utils'

export const pipelineDestinationsLogic = kea<pipelineDestinationsLogicType>([
    path(['scenes', 'pipeline', 'destinationsLogic']),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            pipelineAccessLogic,
            ['canEnableNewDestinations'],
        ],
    }),
    actions({
        toggleNode: (destination: Destination, enabled: boolean) => ({ destination, enabled }),
        deleteNode: (destination: Destination) => ({ destination }),
        deleteNodeBatchExport: (destination: BatchExportDestination) => ({ destination }),
        updatePluginConfig: (pluginConfig: PluginConfigTypeNew) => ({ pluginConfig }),
        updateBatchExportConfig: (batchExportConfig: BatchExportConfiguration) => ({ batchExportConfig }),
    }),
    loaders(({ values }) => ({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
                    return loadPluginsFromUrl('api/organizations/@current/pipeline_destinations')
                },
            },
        ],
        pluginConfigs: [
            {} as Record<number, PluginConfigTypeNew>,
            {
                loadPluginConfigs: async () => {
                    const pluginConfigs: Record<number, PluginConfigTypeNew> = {}
                    const results = await api.loadPaginatedResults<PluginConfigTypeNew>(
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
                toggleNodeWebhook: async ({ destination, enabled }) => {
                    const { pluginConfigs, plugins } = values
                    const pluginConfig = pluginConfigs[destination.id]
                    const plugin = plugins[pluginConfig.plugin]
                    capturePluginEvent(`plugin ${enabled ? 'enabled' : 'disabled'}`, plugin, pluginConfig)
                    const response = await api.update(`api/plugin_config/${destination.id}`, {
                        enabled,
                    })
                    return { ...pluginConfigs, [destination.id]: response }
                },
                updatePluginConfig: ({ pluginConfig }) => {
                    return {
                        ...values.pluginConfigs,
                        [pluginConfig.id]: pluginConfig,
                    }
                },
            },
        ],
        batchExportConfigs: [
            {} as Record<string, BatchExportConfiguration>,
            {
                loadBatchExports: async () => {
                    const results = await api.loadPaginatedResults<BatchExportConfiguration>(
                        `api/projects/${values.currentTeamId}/batch_exports`
                    )
                    return Object.fromEntries(results.map((batchExport) => [batchExport.id, batchExport]))
                },
                toggleNodeBatchExport: async ({ destination, enabled }) => {
                    const batchExport = values.batchExportConfigs[destination.id]
                    if (enabled) {
                        await api.batchExports.unpause(destination.id)
                    } else {
                        await api.batchExports.pause(destination.id)
                    }
                    captureBatchExportEvent(`batch export ${enabled ? 'enabled' : 'disabled'}`, batchExport)
                    return { ...values.batchExportConfigs, [destination.id]: { ...batchExport, paused: !enabled } }
                },
                deleteNodeBatchExport: async ({ destination }) => {
                    await api.batchExports.delete(destination.id)
                    return Object.fromEntries(
                        Object.entries(values.batchExportConfigs).filter(([id]) => id !== destination.id)
                    )
                },
                updateBatchExportConfig: ({ batchExportConfig }) => {
                    return { ...values.batchExportConfigs, [batchExportConfig.id]: batchExportConfig }
                },
            },
        ],

        hogFunctionTemplates: [
            {} as Record<string, HogFunctionTemplateType>,
            {
                loadHogFunctionTemplates: async () => {
                    return HOG_FUNCTION_TEMPLATES.reduce((acc, template) => {
                        acc[template.id] = template
                        return acc
                    }, {} as Record<string, HogFunctionTemplateType>)
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [
                s.pluginsLoading,
                s.pluginConfigsLoading,
                s.batchExportConfigsLoading,
                s.hogFunctionTemplatesLoading,
            ],
            (pluginsLoading, pluginConfigsLoading, batchExportConfigsLoading, hogFunctionTemplatesLoading) =>
                pluginsLoading || pluginConfigsLoading || batchExportConfigsLoading || hogFunctionTemplatesLoading,
        ],
        destinations: [
            (s) => [s.pluginConfigs, s.plugins, s.batchExportConfigs, s.user],
            (pluginConfigs, plugins, batchExportConfigs, user): Destination[] => {
                // Migrations are shown only in impersonation mode, for us to be able to trigger them.
                const rawBatchExports = Object.values(batchExportConfigs).filter(
                    (config) => config.destination.type !== 'HTTP' || user?.is_impersonated
                )
                const rawDestinations: (PluginConfigWithPluginInfoNew | BatchExportConfiguration)[] = Object.values(
                    pluginConfigs
                )
                    .map<PluginConfigWithPluginInfoNew | BatchExportConfiguration>((pluginConfig) => ({
                        ...pluginConfig,
                        plugin_info: plugins[pluginConfig.plugin] || null,
                    }))
                    .concat(rawBatchExports)
                const convertedDestinations = rawDestinations.map((d) =>
                    convertToPipelineNode(d, PipelineStage.Destination)
                )
                const enabledFirst = convertedDestinations.sort((a, b) => Number(b.enabled) - Number(a.enabled))
                return enabledFirst
            },
        ],
        shouldShowProductIntroduction: [
            (s) => [s.user],
            (user): boolean => {
                return !user?.has_seen_product_intro_for?.[ProductKey.PIPELINE_DESTINATIONS]
            },
        ],
    }),
    listeners(({ values, actions, asyncActions }) => ({
        toggleNode: ({ destination, enabled }) => {
            if (enabled && !values.canEnableNewDestinations) {
                lemonToast.error('Data pipelines add-on is required for enabling new destinations.')
                return
            }
            if (destination.backend === PipelineBackend.Plugin) {
                actions.toggleNodeWebhook({ destination: destination, enabled: enabled })
            } else {
                actions.toggleNodeBatchExport({ destination: destination, enabled: enabled })
            }
        },
        deleteNode: async ({ destination }) => {
            if (destination.backend === PipelineBackend.BatchExport) {
                await asyncActions.deleteNodeBatchExport(destination)
            } else {
                await deleteWithUndo({
                    endpoint: `projects/${teamLogic.values.currentTeamId}/plugin_configs`,
                    object: {
                        id: destination.id,
                        name: destination.name,
                    },
                    callback: actions.loadPluginConfigs,
                })
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadPluginConfigs()
        actions.loadBatchExports()
        actions.loadHogFunctionTemplates()
    }),
])
