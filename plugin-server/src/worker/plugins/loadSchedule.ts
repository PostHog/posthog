import { Summary } from 'prom-client'

import { Hub, PluginConfigId } from '../../types'
import { status } from '../../utils/status'

const loadScheduleMsSummary = new Summary({
    name: 'load_schedule_ms',
    help: 'Time to load schedule',
})

export async function loadSchedule(server: Hub): Promise<void> {
    const timer = new Date()
    server.pluginSchedule = null

    // gather runEvery* tasks into a schedule
    const pluginSchedule: Record<string, PluginConfigId[]> = { runEveryMinute: [], runEveryHour: [], runEveryDay: [] }

    let count = 0

    for (const [id, pluginConfig] of server.pluginConfigs) {
        const tasks = (await pluginConfig.instance?.getScheduledTasks()) ?? {}
        for (const [taskName, task] of Object.entries(tasks)) {
            if (task && taskName in pluginSchedule) {
                pluginSchedule[taskName].push(id)
                count++
            }
        }
    }

    if (count > 0) {
        status.info('🔌', `Loaded ${count} scheduled tasks`)
    }

    server.pluginSchedule = pluginSchedule
    loadScheduleMsSummary.observe(new Date().getTime() - timer.getTime())
}
