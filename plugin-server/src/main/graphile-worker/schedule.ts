import { Hub, PluginConfigId } from '../../types'
import { status } from '../../utils/status'
import { workerTasks } from '../../worker/tasks'

export async function loadPluginSchedule(hub: Hub): Promise<Hub['pluginSchedule']> {
    // Having ensured the schedule is loaded on all threads, pull it from only one of them
    const schedule = (await workerTasks['getPluginSchedule'](hub, {})) as Record<string, PluginConfigId[]> | null
    return schedule
}

export async function runScheduledTasks(server: Hub, taskType: string): Promise<void> {
    for (const pluginConfigId of server.pluginSchedule?.[taskType] || []) {
        status.info('⏲️', `Running ${taskType} for plugin config with ID ${pluginConfigId}`)
        await workerTasks[taskType](server, { pluginConfigId })
    }
}
