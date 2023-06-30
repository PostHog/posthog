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
        if (pluginConfig.plugin?.capabilities?.scheduled_tasks?.length) {
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
