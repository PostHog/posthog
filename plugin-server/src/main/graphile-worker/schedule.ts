import Piscina from '@posthog/piscina'

import { Hub, PluginConfigId } from '../../types'
import { status } from '../../utils/status'
import { delay } from '../../utils/utils'

export async function loadPluginSchedule(piscina: Piscina, maxIterations = 2000): Promise<Hub['pluginSchedule']> {
    let allThreadsReady = false
    while (maxIterations--) {
        // Make sure the schedule loaded successfully on all threads
        if (!allThreadsReady) {
            const threadsScheduleReady = await piscina.broadcastTask({ task: 'pluginScheduleReady' })
            allThreadsReady = threadsScheduleReady.every((res) => res)
        }

        if (allThreadsReady) {
            // Having ensured the schedule is loaded on all threads, pull it from only one of them
            const schedule = (await piscina.run({ task: 'getPluginSchedule' })) as Record<
                string,
                PluginConfigId[]
            > | null
            if (schedule) {
                return schedule
            }
        }
        await delay(200)
    }
    throw new Error('Could not load plugin schedule in time')
}

export async function runScheduledTasks(server: Hub, piscina: Piscina, taskType: string): Promise<void> {
    for (const pluginConfigId of server.pluginSchedule?.[taskType] || []) {
        status.info('⏲️', `Running ${taskType} for plugin config with ID ${pluginConfigId}`)
        await piscina.run({ task: taskType, args: { pluginConfigId } })
    }
}
