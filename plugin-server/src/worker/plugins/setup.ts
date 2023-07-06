import { Hub, PluginLogEntrySource, PluginLogEntryType, StatelessVmMap } from '../../types'
import { LazyPluginVM } from '../vm/lazy'
import { loadPlugin } from './loadPlugin'
import { loadPluginsFromDB } from './loadPluginsFromDB'
import { loadSchedule } from './loadSchedule'
import { teardownPlugins } from './teardown'

export async function setupPlugins(hub: Hub): Promise<void> {
    const { plugins, pluginConfigs, pluginConfigsPerTeam } = await loadPluginsFromDB(hub)
    const pluginVMLoadPromises: Array<Promise<any>> = []
    const statelessVms = {} as StatelessVmMap

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

            // For anything other than the ingestion pods or overflow pods, we need to
            // load everything.
            //
            // For scheduler, we need to load all the scheduler plugins as we do not
            // know what the capabilities are before the first time we have loaded a
            // plugin. This is because the capabilities column in the plugin table
            // is only updated when the plugin is loaded.
            //
            // A more sustainable solution would be to have Django send a message to
            // Kafka then a plugin is update and have e.g. the scheduler, or the
            // graphile job worker process, listen to that message and update the
            // capabilities column in the plugin table, as well as transpiling the
            // plugin.
            //
            // We can then e.g. send a signal that the plugin has been updated and
            // the plugin servers should reload it. Once we can rely on the data in
            // postgres to be up to date we can then narrow down the query we use to
            // load the plugin and plugin config data by e.g. filtering on
            // `'schedules' in capabilities` of something along those lines.
            //
            // It would be wise to have a way of identifying the date at which the
            // plugin was last updated via the process described above, so that we
            // can avoid reloading the plugin if it has not been updated since the
            // last time we loaded it.
            //
            // For now we just use the blunt instrument of loading all the plugins
            // for some plugin-server instances.
            if (!hub.capabilities.ingestion && !hub.capabilities.ingestionOverflow) {
                pluginVMLoadPromises.push(loadPlugin(hub, pluginConfig))
            }

            if (prevConfig) {
                void teardownPlugins(hub, prevConfig)
            }

            if (plugin?.is_stateless) {
                statelessVms[plugin.id] = pluginConfig.vm
            }
        }

        await hub.db.queuePluginLogEntry({
            message: `Plugin registered (instance ID ${hub.instanceId}).`,
            pluginConfig: pluginConfig,
            source: PluginLogEntrySource.System,
            type: PluginLogEntryType.Debug,
            instanceId: hub.instanceId,
        })
    }

    await Promise.all(pluginVMLoadPromises)
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
