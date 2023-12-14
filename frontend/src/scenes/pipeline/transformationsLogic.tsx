import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { canConfigurePlugins } from 'scenes/plugins/access'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { PluginConfigTypeNew, PluginType, ProductKey } from '~/types'

import type { pipelineTransformationsLogicType } from './transformationsLogicType'
import { capturePluginEvent } from './utils'

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
    }),
    loaders(({ values }) => ({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
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
                    const res: PluginConfigTypeNew[] = await api.loadPaginatedResults(
                        `api/projects/${values.currentTeamId}/pipeline_transformations_configs`
                    )

                    return Object.fromEntries(res.map((pluginConfig) => [pluginConfig.id, pluginConfig]))
                },
                savePluginConfigsOrder: async ({ newOrders }) => {
                    if (!values.canConfigurePlugins) {
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
                    if (!values.canConfigurePlugins) {
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
                        const maxOrder = Math.max(
                            ...Object.values(values.enabledPluginConfigs).map((pc) => pc.order),
                            0
                        )
                        order = { order: maxOrder + 1 }
                    }
                    const response = await api.update(`api/plugin_config/${id}`, {
                        enabled,
                        ...order,
                    })
                    return { ...pluginConfigs, [id]: response }
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.pluginsLoading, s.pluginConfigsLoading],
            (pluginsLoading, pluginConfigsLoading) => pluginsLoading || pluginConfigsLoading,
        ],
        enabledPluginConfigs: [
            (s) => [s.pluginConfigs],
            (pluginConfigs) => {
                return Object.values(pluginConfigs).filter((pc) => pc.enabled)
            },
        ],
        sortedEnabledPluginConfigs: [
            (s) => [s.pluginConfigs, s.enabledPluginConfigs, s.temporaryOrder],
            (pluginConfigs, enabledPluginConfigs, temporaryOrder) => {
                if (!temporaryOrder || Object.keys(temporaryOrder).length === 0) {
                    return enabledPluginConfigs.sort((a, b) => a.order - b.order)
                }
                // If temp order is set return the pluginConfigs in that order
                const result = Object.entries(temporaryOrder)
                    .sort(([, aIdx], [, bIdx]) => aIdx - bIdx)
                    .map(([pluginId]) => pluginConfigs[Number(pluginId)])
                return result
            },
        ],
        disabledPluginConfigs: [
            (s) => [s.pluginConfigs],
            (pluginConfigs) => Object.values(pluginConfigs).filter((pc) => !pc.enabled),
        ],
        // This is currently an organization level setting but might in the future be user level
        // it's better to add the permission checks everywhere now
        canConfigurePlugins: [(s) => [s.user], (user) => canConfigurePlugins(user?.organization)],
        shouldShowProductIntroduction: [
            (s) => [s.user],
            (user): boolean => {
                return !user?.has_seen_product_intro_for?.[ProductKey.PIPELINE_TRANSFORMATIONS]
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
