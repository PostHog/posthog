import Piscina from '@posthog/piscina'
import * as schedule from 'node-schedule'

import { Hub, PluginConfigId, PluginScheduleControl } from '../../types'
import { processError } from '../../utils/db/error'
import { cancelAllScheduledJobs } from '../../utils/node-schedule'
import { startRedlock } from '../../utils/redlock'
import { status } from '../../utils/status'
import { delay } from '../../utils/utils'

export const LOCKED_RESOURCE = 'plugin-server:locks:schedule'

export async function startPluginSchedules(
    server: Hub,
    piscina: Piscina,
    onLock?: () => void
): Promise<PluginScheduleControl> {
    status.info('⏰', 'Starting scheduling service...')

    // Import this just to trigger build on ts-node-dev
    // This is a total hack and needs to be fixed - seems to be bug with ts-node-dev
    require('../../worker/worker')

    let stopped = false
    let weHaveTheLock = false

    let pluginSchedulePromise = loadPluginSchedule(piscina)
    server.pluginSchedule = await pluginSchedulePromise

    schedule.scheduleJob('* * * * *', async () => {
        !stopped &&
            weHaveTheLock &&
            (await pluginSchedulePromise) &&
            runScheduleDebounced(server!, piscina!, 'runEveryMinute')
    })
    schedule.scheduleJob('0 * * * *', async () => {
        !stopped &&
            weHaveTheLock &&
            (await pluginSchedulePromise) &&
            runScheduleDebounced(server!, piscina!, 'runEveryHour')
    })
    schedule.scheduleJob('0 0 * * *', async () => {
        !stopped &&
            weHaveTheLock &&
            (await pluginSchedulePromise) &&
            runScheduleDebounced(server!, piscina!, 'runEveryDay')
    })

    const unlock = await startRedlock({
        server,
        resource: LOCKED_RESOURCE,
        onLock: () => {
            weHaveTheLock = true
            onLock?.()
        },
        onUnlock: () => {
            weHaveTheLock = false
        },
        ttl: server.SCHEDULE_LOCK_TTL,
    })

    const stopSchedule = async () => {
        stopped = true
        cancelAllScheduledJobs()

        await unlock()
        await waitForTasksToFinish(server)
    }

    const reloadSchedule = async () => {
        await piscina.broadcastTask({ task: 'reloadSchedule' })
        pluginSchedulePromise = loadPluginSchedule(piscina)
        server.pluginSchedule = await pluginSchedulePromise
    }

    return { stopSchedule, reloadSchedule }
}

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

export function runScheduleDebounced(server: Hub, piscina: Piscina, taskName: string): void {
    const runTask = (pluginConfigId: PluginConfigId) => piscina.run({ task: taskName, args: { pluginConfigId } })

    for (const pluginConfigId of server.pluginSchedule?.[taskName] || []) {
        // last task still running? skip rerunning!
        if (server.pluginSchedulePromises[taskName][pluginConfigId]) {
            continue
        }

        const promise = runTask(pluginConfigId)
        server.pluginSchedulePromises[taskName][pluginConfigId] = promise

        promise
            .then(() => {
                server.pluginSchedulePromises[taskName][pluginConfigId] = null
            })
            .catch(async (error) => {
                await processError(server, server.pluginConfigs.get(pluginConfigId) || null, error)
                server.pluginSchedulePromises[taskName][pluginConfigId] = null
            })
    }
}

export async function waitForTasksToFinish(server: Hub): Promise<any[]> {
    const activePromises = Object.values(server.pluginSchedulePromises)
        .map(Object.values)
        .flat()
        .filter((a) => a)
    return Promise.all(activePromises)
}
