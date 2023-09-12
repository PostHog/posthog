import { rateLimit } from 'prom-utils'

import { Hub, StatelessVmMap } from '../../types'
import { LazyPluginVM } from '../vm/lazy'
import { loadPlugin } from './loadPlugin'
import { loadPluginsFromDB } from './loadPluginsFromDB'
import { loadSchedule } from './loadSchedule'
import { teardownPlugins } from './teardown'

export async function setupPlugins(hub: Hub): Promise<void> {
    const { plugins, pluginConfigs, pluginConfigsPerTeam } = await loadPluginsFromDB(hub)
    const statelessVms = {} as StatelessVmMap

    const limiter = rateLimit(hub.PLUGIN_LOAD_CONCURRENCY)
    const timer = new Date()

    for (const [id, pluginConfig] of pluginConfigs) {
        const plugin = plugins.get(pluginConfig.plugin_id)
        const prevConfig = hub.pluginConfigs.get(id)
        const prevPlugin = prevConfig ? hub.plugins.get(pluginConfig.plugin_id) : null

        const pluginConfigChanged = !prevConfig || pluginConfig.updated_at !== prevConfig.updated_at
        const pluginChanged = plugin?.updated_at !== prevPlugin?.updated_at

        if (!pluginConfigChanged && !pluginChanged) {
            pluginConfig.vm = prevConfig.vm
        } else if (plugin?.is_stateless && statelessVms[plugin.id]) {
            pluginConfig.vm = statelessVms[plugin.id]
        } else {
            pluginConfig.vm = new LazyPluginVM(hub, pluginConfig)
            await limiter.add(loadPlugin(hub, pluginConfig)) // Will block if PLUGIN_LOAD_CONCURRENCY is reached

            if (prevConfig) {
                void teardownPlugins(hub, prevConfig)
            }

            if (plugin?.is_stateless) {
                statelessVms[plugin.id] = pluginConfig.vm
            }
        }
    }

    await limiter.finish()
    hub.statsd?.timing('setup_plugins.success', timer)

    hub.plugins = plugins
    hub.pluginConfigs = pluginConfigs
    hub.pluginConfigsPerTeam = pluginConfigsPerTeam

    for (const teamId of hub.pluginConfigsPerTeam.keys()) {
        hub.pluginConfigsPerTeam.get(teamId)?.sort((a, b) => a.order - b.order)
    }

    // Only load the schedule in server that can process scheduled tasks, else the schedule won't be useful
    if (hub.capabilities.pluginScheduledTasks) {
        await loadSchedule(hub)
    }
}
