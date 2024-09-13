import { lemonToast } from '@posthog/lemon-ui'
import FuseClass from 'fuse.js'
import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    BatchExportConfiguration,
    HogFunctionType,
    PipelineStage,
    PluginConfigTypeNew,
    PluginConfigWithPluginInfoNew,
    PluginType,
} from '~/types'

import { pipelineAccessLogic } from '../pipelineAccessLogic'
import {
    BatchExportDestination,
    convertToPipelineNode,
    Destination,
    FunctionDestination,
    PipelineBackend,
    WebhookDestination,
} from '../types'
import { captureBatchExportEvent, capturePluginEvent, loadPluginsFromUrl } from '../utils'
import { destinationsFiltersLogic } from './destinationsFiltersLogic'
import type { pipelineDestinationsLogicType } from './destinationsLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<Destination> {}

export const pipelineDestinationsLogic = kea<pipelineDestinationsLogicType>([
    path(['scenes', 'pipeline', 'destinationsLogic']),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            pipelineAccessLogic,
            ['canEnableDestination'],
            featureFlagLogic,
            ['featureFlags'],
            destinationsFiltersLogic,
            ['filters'],
        ],
    }),
    actions({
        toggleNode: (destination: Destination, enabled: boolean) => ({ destination, enabled }),
        toggleNodeHogFunction: (destination: FunctionDestination, enabled: boolean) => ({ destination, enabled }),
        deleteNode: (destination: Destination) => ({ destination }),
        deleteNodeBatchExport: (destination: BatchExportDestination) => ({ destination }),
        deleteNodeHogFunction: (destination: FunctionDestination) => ({ destination }),
        deleteNodeWebhook: (destination: WebhookDestination) => ({ destination }),

        updatePluginConfig: (pluginConfig: PluginConfigTypeNew) => ({ pluginConfig }),
        updateBatchExportConfig: (batchExportConfig: BatchExportConfiguration) => ({ batchExportConfig }),
    }),
    loaders(({ values, actions }) => ({
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

                deleteNodeWebhook: async ({ destination }) => {
                    await deleteWithUndo({
                        endpoint: `projects/${teamLogic.values.currentTeamId}/plugin_configs`,
                        object: {
                            id: destination.id,
                            name: destination.name,
                        },
                        callback: (undo) => {
                            if (undo) {
                                actions.loadPluginConfigs()
                            }
                        },
                    })

                    const pluginConfigs = { ...values.pluginConfigs }
                    delete pluginConfigs[destination.id]

                    return pluginConfigs
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

                    const batchExportConfigs = { ...values.batchExportConfigs }
                    delete batchExportConfigs[destination.id]

                    return batchExportConfigs
                },
                updateBatchExportConfig: ({ batchExportConfig }) => {
                    return { ...values.batchExportConfigs, [batchExportConfig.id]: batchExportConfig }
                },
            },
        ],

        hogFunctions: [
            [] as HogFunctionType[],
            {
                loadHogFunctions: async () => {
                    // TODO: Support pagination?
                    return (await api.hogFunctions.list()).results
                },

                deleteNodeHogFunction: async ({ destination }) => {
                    if (destination.backend !== PipelineBackend.HogFunction) {
                        return values.hogFunctions
                    }

                    await deleteWithUndo({
                        endpoint: `projects/${teamLogic.values.currentTeamId}/hog_functions`,
                        object: {
                            id: destination.hog_function.id,
                            name: destination.name,
                        },
                        callback: (undo) => {
                            if (undo) {
                                actions.loadHogFunctions()
                            }
                        },
                    })

                    return values.hogFunctions.filter((hogFunction) => hogFunction.id !== destination.hog_function.id)
                },
                toggleNodeHogFunction: async ({ destination, enabled }) => {
                    const { hogFunctions } = values
                    const hogFunctionIndex = hogFunctions.findIndex((hf) => hf.id === destination.hog_function.id)
                    const response = await api.hogFunctions.update(destination.hog_function.id, {
                        enabled,
                    })
                    return [
                        ...hogFunctions.slice(0, hogFunctionIndex),
                        response,
                        ...hogFunctions.slice(hogFunctionIndex + 1),
                    ]
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.pluginsLoading, s.pluginConfigsLoading, s.batchExportConfigsLoading, s.hogFunctionsLoading],
            (pluginsLoading, pluginConfigsLoading, batchExportConfigsLoading, hogFunctionsLoading) =>
                pluginsLoading || pluginConfigsLoading || batchExportConfigsLoading || hogFunctionsLoading,
        ],
        destinations: [
            (s) => [s.pluginConfigs, s.plugins, s.batchExportConfigs, s.hogFunctions, s.user, s.featureFlags],
            (pluginConfigs, plugins, batchExportConfigs, hogFunctions, user, featureFlags): Destination[] => {
                // Migrations are shown only in impersonation mode, for us to be able to trigger them.
                const httpEnabled =
                    featureFlags[FEATURE_FLAGS.BATCH_EXPORTS_POSTHOG_HTTP] || user?.is_impersonated || user?.is_staff

                const rawBatchExports = Object.values(batchExportConfigs).filter((config) =>
                    httpEnabled ? true : config.destination.type !== ('HTTP' as const)
                )

                const rawDestinations: (PluginConfigWithPluginInfoNew | BatchExportConfiguration | HogFunctionType)[] =
                    ([] as (PluginConfigWithPluginInfoNew | BatchExportConfiguration | HogFunctionType)[])
                        .concat(hogFunctions)
                        .concat(
                            Object.values(pluginConfigs).map((pluginConfig) => ({
                                ...pluginConfig,
                                plugin_info: plugins[pluginConfig.plugin] || null,
                            }))
                        )
                        .concat(rawBatchExports)
                const convertedDestinations = rawDestinations.map((d) =>
                    convertToPipelineNode(d, PipelineStage.Destination)
                )
                const enabledFirst = convertedDestinations.sort((a, b) => Number(b.enabled) - Number(a.enabled))
                return enabledFirst
            },
        ],
        destinationsFuse: [
            (s) => [s.destinations],
            (destinations): Fuse => {
                return new FuseClass(destinations || [], {
                    keys: ['name', 'description'],
                    threshold: 0.3,
                })
            },
        ],

        filteredDestinations: [
            (s) => [s.filters, s.destinations, s.destinationsFuse],
            (filters, destinations, destinationsFuse): Destination[] => {
                const { search, showPaused, kind } = filters

                return (search ? destinationsFuse.search(search).map((x) => x.item) : destinations).filter((dest) => {
                    if (kind && dest.backend !== kind) {
                        return false
                    }
                    if (!showPaused && !dest.enabled) {
                        return false
                    }
                    return true
                })
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        toggleNode: ({ destination, enabled }) => {
            if (enabled && !values.canEnableDestination(destination)) {
                lemonToast.error('Data pipelines add-on is required for enabling new destinations.')
                return
            }
            if (destination.backend === PipelineBackend.Plugin) {
                actions.toggleNodeWebhook({ destination: destination, enabled: enabled })
            } else if (destination.backend === PipelineBackend.BatchExport) {
                actions.toggleNodeBatchExport({ destination: destination, enabled: enabled })
            } else if (destination.backend === PipelineBackend.HogFunction) {
                actions.toggleNodeHogFunction(destination, enabled)
            }
        },
        deleteNode: ({ destination }) => {
            switch (destination.backend) {
                case PipelineBackend.Plugin:
                    actions.deleteNodeWebhook(destination)
                    break
                case PipelineBackend.BatchExport:
                    actions.deleteNodeBatchExport(destination)
                    break
                case PipelineBackend.HogFunction:
                    actions.deleteNodeHogFunction(destination)
                    break
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadPluginConfigs()
        actions.loadBatchExports()
        actions.loadHogFunctions()
    }),
])
