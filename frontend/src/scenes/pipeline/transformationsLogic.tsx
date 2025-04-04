import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { PipelineStage, PluginConfigTypeNew, PluginConfigWithPluginInfoNew, PluginType } from '~/types'

import type { pipelineTransformationsLogicType } from './transformationsLogicType'
import { convertToPipelineNode, Transformation } from './types'
import { capturePluginEvent, checkPermissions, loadPluginsFromUrl } from './utils'

export const pipelineTransformationsLogic = kea<pipelineTransformationsLogicType>([
    path(['scenes', 'pipeline', 'transformationsLogic']),
    connect({
        values: [teamLogic, ['currentTeamId'], userLogic, ['user']],
    }),
    actions({
        loadPluginConfigs: true,
        openReorderModal: true,
        closeReorderModal: true,
        setTemporaryOrder: (tempOrder: Record<number, number>) => ({
            tempOrder,
        }),
        savePluginConfigsOrder: (newOrders: Record<number, number>) => ({ newOrders }),
        updatePluginConfig: (pluginConfig: PluginConfigTypeNew) => ({ pluginConfig }),
    }),
    loaders(({ values }) => ({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
                    return loadPluginsFromUrl('api/organizations/@current/pipeline_transformations')
                },
            },
        ],
        temporaryOrder: [
            // empty or all enabled plugins map: plugin-id to order
            {} as Record<number, number>,
            {
                setTemporaryOrder: async ({ tempOrder }) => tempOrder,
                closeReorderModal: async () => ({}),
            },
        ],
        pluginConfigs: [
            {} as Record<number, PluginConfigTypeNew>,
            {
                loadPluginConfigs: async () => {
                    const res = await api.loadPaginatedResults<PluginConfigTypeNew>(
                        `api/projects/${values.currentTeamId}/pipeline_transformation_configs`
                    )

                    return Object.fromEntries(res.map((pluginConfig) => [pluginConfig.id, pluginConfig]))
                },
                savePluginConfigsOrder: async ({ newOrders }) => {
                    if (!checkPermissions(PipelineStage.Transformation, false)) {
                        return values.pluginConfigs
                    }
                    // Plugin-server sorts by order and runs the plugins in that order
                    // we assume that there are no two enabled transformation plugins that have the same order value
                    // But that's not true, see http://metabase-prod-us/question/341-processevent-plugins-ran-in-undetermined-order
                    // We have races across enabling (ui and django admin) and reorder modal,
                    // where parallel requests can result in the same order used for multiple plugins
                    // TODO: maybe show warning if order match exist and allow to resolve them
                    const { pluginConfigs } = values
                    const response: PluginConfigTypeNew[] = await api.update(`api/plugin_config/rearrange`, {
                        orders: newOrders,
                    })

                    const newPluginConfigs: Record<number, PluginConfigTypeNew> = { ...pluginConfigs }
                    for (const pluginConfig of response) {
                        // Rearrange currently returns all plugins not just processEvent plugins
                        // so we need to filter out the non processEvent plugins, which is easiest done if we filter by
                        // plugins loaded, alternatively we could just load plugin configs again from scratch.
                        if (Object.keys(values.plugins).map(Number).includes(pluginConfig.plugin)) {
                            newPluginConfigs[pluginConfig.id] = pluginConfig
                        }
                    }
                    return newPluginConfigs
                },
                toggleEnabled: async ({ id, enabled }) => {
                    if (!checkPermissions(PipelineStage.Transformation, enabled)) {
                        return values.pluginConfigs
                    }
                    const { pluginConfigs, plugins } = values
                    const pluginConfig = pluginConfigs[id]
                    const plugin = plugins[pluginConfig.plugin]
                    capturePluginEvent(`plugin ${enabled ? 'enabled' : 'disabled'}`, plugin, pluginConfig)
                    // Update order if enabling to be at the end of current enabled plugins
                    // See comment in savePluginConfigsOrder about races
                    let order = {}
                    if (enabled) {
                        order = { order: values.nextAvailableOrder }
                    }
                    const response = await api.update(`api/plugin_config/${id}`, {
                        enabled,
                        ...order,
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
        transformations: [
            (s) => [s.pluginConfigs, s.plugins],
            (pluginConfigs, plugins): Transformation[] => {
                const rawTransformations: PluginConfigWithPluginInfoNew[] = Object.values(
                    pluginConfigs
                ).map<PluginConfigWithPluginInfoNew>((pluginConfig) => ({
                    ...pluginConfig,
                    plugin_info: plugins[pluginConfig.plugin] || null,
                }))
                const convertedTransformations = rawTransformations.map((t) =>
                    convertToPipelineNode(t, PipelineStage.Transformation)
                )
                return convertedTransformations
            },
        ],
        sortedEnabledTransformations: [
            (s) => [s.transformations, s.temporaryOrder],
            (transformations, temporaryOrder) => {
                transformations = transformations.filter((t) => t.enabled)
                if (temporaryOrder && Object.keys(temporaryOrder).length > 0) {
                    transformations = Object.entries(temporaryOrder)
                        .sort(([, aIdx], [, bIdx]) => aIdx - bIdx)
                        .map(([pluginId]) => transformations.find((t) => t.id === Number(pluginId)) as Transformation)
                } else {
                    transformations = transformations.sort((a, b) => a.order - b.order)
                }
                return transformations
            },
        ],
        sortedTransformations: [
            (s) => [s.transformations, s.sortedEnabledTransformations],
            (transformations, sortedEnabledTransformations) => {
                return sortedEnabledTransformations.concat(
                    transformations.filter((t) => !t.enabled).sort((a, b) => a.id - b.id)
                )
            },
        ],
        nextAvailableOrder: [
            (s) => [s.transformations],
            (transformations): number => {
                const enabledTransformations = transformations.filter((t) => t.enabled)
                return enabledTransformations.length > 0
                    ? Math.max(...enabledTransformations.map((t) => t.order), 0) + 1
                    : 0
            },
        ],
    }),
    reducers({
        reorderModalOpen: [
            false,
            {
                openReorderModal: () => true,
                closeReorderModal: () => false,
            },
        ],
    }),
    listeners(({ actions }) => ({
        savePluginConfigsOrderSuccess: () => {
            actions.closeReorderModal()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadPluginConfigs()
    }),
])
