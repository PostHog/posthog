import { Hub, PluginConfigId } from '../../types'
import { status } from '../../utils/status'
import { loadPlugin } from './loadPlugin'

export async function loadSchedule(server: Hub): Promise<void> {
    const timer = new Date()
    server.pluginSchedule = null

    // gather runEvery* tasks into a schedule
    const pluginSchedule: Record<string, PluginConfigId[]> = { runEveryMinute: [], runEveryHour: [], runEveryDay: [] }

    let count = 0

    for (const [id, pluginConfig] of server.pluginConfigs) {
        // A very basic check to see if the plugin has a scheduled task.
        // To be able to populate the capabilities, we need to load the plugin.
        // This check may catch some plugins that don't have a scheduled task,
        // but it's better than loading all plugins.
        if (pluginConfig.plugin?.source__index_ts?.includes('runEvery')) {
            await loadPlugin(server, pluginConfig)
            const tasks = (await pluginConfig.vm?.getScheduledTasks()) ?? {}
            for (const [taskName, task] of Object.entries(tasks)) {
                if (task && taskName in pluginSchedule) {
                    pluginSchedule[taskName].push(id)
                    count++
                }
            }
        }
    }

    if (count > 0) {
        status.info('🔌', `Loaded ${count} scheduled tasks`)
    }

    server.pluginSchedule = pluginSchedule
    server.statsd?.timing('load_schedule.success', timer)
}
