import { Gauge, Summary } from 'prom-client'

import { Hub, StatelessInstanceMap } from '../../types'
import { logger } from '../../utils/logger'
import { constructPluginInstance } from '../vm/lazy'
import { loadPlugin } from './loadPlugin'
import { loadPluginsFromDB } from './loadPluginsFromDB'
import { teardownPlugins } from './teardown'

export const importUsedGauge = new Gauge({
    name: 'plugin_import_used',
    help: 'Imports used by plugins, broken down by import name and plugin_id',
    labelNames: ['name', 'plugin_id'],
})
const setupPluginsMsSummary = new Summary({
    name: 'setup_plugins_ms',
    help: 'Time to setup plugins',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export async function setupPlugins(hub: Hub): Promise<void> {
    const startTime = Date.now()
    logger.info('🔁', `Loading plugin configs...`)
    const { plugins, pluginConfigs, pluginConfigsPerTeam } = await loadPluginsFromDB(hub)
    const pluginVMLoadPromises: Array<Promise<any>> = []
    const statelessInstances = {} as StatelessInstanceMap

    const timer = new Date()

    for (const [id, pluginConfig] of pluginConfigs) {
        const plugin = plugins.get(pluginConfig.plugin_id)
        const prevConfig = hub.pluginConfigs.get(id)
        const prevPlugin = prevConfig ? hub.plugins.get(pluginConfig.plugin_id) : null

        const pluginConfigChanged = !prevConfig || pluginConfig.updated_at !== prevConfig.updated_at
        const pluginChanged = plugin?.updated_at !== prevPlugin?.updated_at

        if (!pluginConfigChanged && !pluginChanged) {
            pluginConfig.instance = prevConfig.instance
        } else if (plugin?.is_stateless && statelessInstances[plugin.id]) {
            pluginConfig.instance = statelessInstances[plugin.id]
        } else {
            pluginConfig.instance = constructPluginInstance(hub, pluginConfig)
            if (hub.PLUGIN_LOAD_SEQUENTIALLY) {
                await loadPlugin(hub, pluginConfig)
            } else {
                pluginVMLoadPromises.push(loadPlugin(hub, pluginConfig))
            }
            if (prevConfig) {
                void teardownPlugins(hub, prevConfig)
            }

            if (plugin?.is_stateless) {
                statelessInstances[plugin.id] = pluginConfig.instance
            }
        }
    }

    await Promise.all(pluginVMLoadPromises)
    setupPluginsMsSummary.observe(new Date().getTime() - timer.getTime())

    hub.plugins = plugins
    hub.pluginConfigs = pluginConfigs
    hub.pluginConfigsPerTeam = pluginConfigsPerTeam

    importUsedGauge.reset()
    const seenPlugins = new Set<number>()
    for (const pluginConfig of pluginConfigs.values()) {
        const usedImports = pluginConfig.instance?.usedImports
        if (usedImports && !seenPlugins.has(pluginConfig.plugin_id)) {
            seenPlugins.add(pluginConfig.plugin_id)
            for (const importName of usedImports) {
                importUsedGauge.set({ name: importName, plugin_id: pluginConfig.plugin_id }, 1)
            }
        }
    }

    for (const teamId of hub.pluginConfigsPerTeam.keys()) {
        hub.pluginConfigsPerTeam.get(teamId)?.sort((a, b) => a.order - b.order)
    }

    logger.info(
        '✅',
        `Loaded ${pluginConfigs.size} configs for ${plugins.size} plugins, took ${Date.now() - startTime}ms`
    )
}
