import Piscina from '@posthog/piscina'

import { Hub, PluginConfigId } from '../../types'
import { status } from '../../utils/status'
import { delay } from '../../utils/utils'
import { PluginScheduledTask } from './../../types'

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

// Triggered by a Graphile Worker cron task
// Enqueue a job per <task,pluginConfigId> combination
// This allows us to spread the load of processing plugin scheduled tasks across the fleet
export async function runScheduledTasks(server: Hub, taskType: PluginScheduledTask): Promise<void> {
    for (const pluginConfigId of server.pluginSchedule?.[taskType] || []) {
        status.info('⬆️', `Scheduling ${taskType} for plugin config with ID ${pluginConfigId}`)

        await server.graphileWorker.enqueue('pluginScheduledTask', {
            pluginConfigId,
            task: taskType,
            timestamp: Date.now(),
        })
    }
}
