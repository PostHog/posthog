import { lemonToast } from '@posthog/lemon-ui'
import FuseClass from 'fuse.js'
import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
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
    HogFunctionTypeType,
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
    SiteApp,
    WebhookDestination,
} from '../types'
import { captureBatchExportEvent, capturePluginEvent, loadPluginsFromUrl } from '../utils'
import { hogFunctionsListFiltersLogic } from './hogFunctionsListFiltersLogic'
import type { hogFunctionsListLogicType } from './hogFunctionsListLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<Destination | SiteApp> {}

export interface HogFunctionsListLogicProps {
    types: HogFunctionTypeType[]
}

export const hogFunctionsListLogic = kea<hogFunctionsListLogicType>([
    path(['scenes', 'pipeline', 'hog-functions-list', 'hogFunctionsListLogic']),
    props({} as HogFunctionsListLogicProps),
    key((props) => props.types.join(',')),
    connect(({ types }: HogFunctionsListLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user', 'hasAvailableFeature'],
            pipelineAccessLogic,
            ['canEnableDestination'],
            featureFlagLogic,
            ['featureFlags'],
            hogFunctionsListFiltersLogic({ types }),
            ['filters'],
        ],
    })),
    actions({
        toggleNode: (func: Destination | SiteApp, enabled: boolean) => ({ func, enabled }),
        toggleNodeHogFunction: (func: FunctionDestination, enabled: boolean) => ({ func, enabled }),
        deleteNode: (func: Destination | SiteApp) => ({ func }),
        deleteNodeBatchExport: (func: BatchExportDestination) => ({ func }),
        deleteNodeHogFunction: (func: FunctionDestination) => ({ func }),
        deleteNodeWebhook: (func: WebhookDestination) => ({ func }),

        updatePluginConfig: (pluginConfig: PluginConfigTypeNew) => ({ pluginConfig }),
        updateBatchExportConfig: (batchExportConfig: BatchExportConfiguration) => ({ batchExportConfig }),
    }),
    loaders(({ values, actions, props }) => ({
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
                toggleNodeWebhook: async ({ func, enabled }) => {
                    const { pluginConfigs, plugins } = values
                    const pluginConfig = pluginConfigs[func.id]
                    const plugin = plugins[pluginConfig.plugin]
                    capturePluginEvent(`plugin ${enabled ? 'enabled' : 'disabled'}`, plugin, pluginConfig)
                    const response = await api.update(`api/plugin_config/${func.id}`, {
                        enabled,
                    })
                    return { ...pluginConfigs, [func.id]: response }
                },
                updatePluginConfig: ({ pluginConfig }) => {
                    return {
                        ...values.pluginConfigs,
                        [pluginConfig.id]: pluginConfig,
                    }
                },

                deleteNodeWebhook: async ({ func }) => {
                    await deleteWithUndo({
                        endpoint: `environments/${teamLogic.values.currentTeamId}/plugin_configs`,
                        object: {
                            id: func.id,
                            name: func.name,
                        },
                        callback: (undo) => {
                            if (undo) {
                                actions.loadPluginConfigs()
                            }
                        },
                    })

                    const pluginConfigs = { ...values.pluginConfigs }
                    delete pluginConfigs[func.id]

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
                toggleNodeBatchExport: async ({ func, enabled }) => {
                    const batchExport = values.batchExportConfigs[func.id]
                    if (enabled) {
                        await api.batchExports.unpause(func.id)
                    } else {
                        await api.batchExports.pause(func.id)
                    }
                    captureBatchExportEvent(`batch export ${enabled ? 'enabled' : 'disabled'}`, batchExport)
                    return { ...values.batchExportConfigs, [func.id]: { ...batchExport, paused: !enabled } }
                },
                deleteNodeBatchExport: async ({ func }) => {
                    await api.batchExports.delete(func.id)

                    const batchExportConfigs = { ...values.batchExportConfigs }
                    delete batchExportConfigs[func.id]

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
                    return (await api.hogFunctions.list(undefined, props.types)).results
                },

                deleteNodeHogFunction: async ({ func }) => {
                    if (func.backend !== PipelineBackend.HogFunction) {
                        return values.hogFunctions
                    }

                    await deleteWithUndo({
                        endpoint: `projects/${teamLogic.values.currentTeamId}/hog_functions`,
                        object: {
                            id: func.hog_function.id,
                            name: func.name,
                        },
                        callback: (undo) => {
                            if (undo) {
                                actions.loadHogFunctions()
                            }
                        },
                    })

                    return values.hogFunctions.filter((hogFunction) => hogFunction.id !== func.hog_function.id)
                },
                toggleNodeHogFunction: async ({ func, enabled }) => {
                    const { hogFunctions } = values
                    const hogFunctionIndex = hogFunctions.findIndex((hf) => hf.id === func.hog_function.id)
                    const response = await api.hogFunctions.update(func.hog_function.id, {
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
        paidHogFunctions: [
            (s) => [s.hogFunctions],
            (hogFunctions) => {
                // Hide disabled functions and free functions. Shown in the "unsubscribe from data pipelines" modal.
                return hogFunctions.filter(
                    (hogFunction) => hogFunction.enabled && hogFunction.template?.status !== 'free'
                )
            },
        ],
        loading: [
            (s) => [s.pluginsLoading, s.pluginConfigsLoading, s.batchExportConfigsLoading, s.hogFunctionsLoading],
            (pluginsLoading, pluginConfigsLoading, batchExportConfigsLoading, hogFunctionsLoading) =>
                pluginsLoading || pluginConfigsLoading || batchExportConfigsLoading || hogFunctionsLoading,
        ],
        functions: [
            (s) => [s.pluginConfigs, s.plugins, s.batchExportConfigs, s.hogFunctions, s.user, s.featureFlags],
            (
                pluginConfigs,
                plugins,
                batchExportConfigs,
                hogFunctions,
                user,
                featureFlags
            ): (Destination | SiteApp)[] => {
                // Migrations are shown only in impersonation mode, for us to be able to trigger them.
                const httpEnabled =
                    featureFlags[FEATURE_FLAGS.BATCH_EXPORTS_POSTHOG_HTTP] || user?.is_impersonated || user?.is_staff

                const rawBatchExports = Object.values(batchExportConfigs).filter((config) =>
                    httpEnabled ? true : config.destination.type !== ('HTTP' as const)
                )

                const rawfunctions: (PluginConfigWithPluginInfoNew | BatchExportConfiguration | HogFunctionType)[] = (
                    [] as (PluginConfigWithPluginInfoNew | BatchExportConfiguration | HogFunctionType)[]
                )
                    .concat(hogFunctions)
                    .concat(
                        Object.values(pluginConfigs).map((pluginConfig) => ({
                            ...pluginConfig,
                            plugin_info: plugins[pluginConfig.plugin] || null,
                        }))
                    )
                    .concat(rawBatchExports)
                const convertedFunctions = rawfunctions.map((d) =>
                    convertToPipelineNode(
                        d,
                        'type' in d && d.type === 'site_app' ? PipelineStage.SiteApp : PipelineStage.Destination
                    )
                )
                const enabledFirst = convertedFunctions.sort((a, b) => Number(b.enabled) - Number(a.enabled))
                return enabledFirst
            },
        ],
        functionsFuse: [
            (s) => [s.functions],
            (functions): Fuse => {
                return new FuseClass(functions || [], {
                    keys: ['name', 'description'],
                    threshold: 0.3,
                })
            },
        ],

        filteredFunctions: [
            (s) => [s.filters, s.functions, s.functionsFuse],
            (filters, functions, functionsFuse): (Destination | SiteApp)[] => {
                const { search, showPaused, kind } = filters

                return (search ? functionsFuse.search(search).map((x) => x.item) : functions).filter((fn) => {
                    if (kind && fn.backend !== kind) {
                        return false
                    }
                    if (!showPaused && !fn.enabled) {
                        return false
                    }
                    return true
                })
            },
        ],

        hiddenFunctions: [
            (s) => [s.functions, s.filteredFunctions],
            (functions, filteredFunctions): (Destination | SiteApp)[] => {
                return functions.filter((fn) => !filteredFunctions.includes(fn))
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        toggleNode: ({ func, enabled }) => {
            if (enabled && !values.canEnableDestination(func)) {
                lemonToast.error('Data pipelines add-on is required for enabling new destinations.')
                return
            }
            if (func.backend === PipelineBackend.Plugin) {
                actions.toggleNodeWebhook({ func, enabled })
            } else if (func.backend === PipelineBackend.BatchExport) {
                actions.toggleNodeBatchExport({ func, enabled })
            } else if (func.backend === PipelineBackend.HogFunction) {
                actions.toggleNodeHogFunction(func, enabled)
            }
        },
        deleteNode: ({ func }) => {
            switch (func.backend) {
                case PipelineBackend.Plugin:
                    actions.deleteNodeWebhook(func as WebhookDestination)
                    break
                case PipelineBackend.BatchExport:
                    actions.deleteNodeBatchExport(func)
                    break
                case PipelineBackend.HogFunction:
                    actions.deleteNodeHogFunction(func)
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
