import Piscina from '@posthog/piscina'
import * as schedule from 'node-schedule'

import { Hub, PluginConfigId, ScheduleControl } from '../../types'
import { processError } from '../../utils/db/error'
import { startRedlock } from '../../utils/redlock'
import { status } from '../../utils/status'
import { delay } from '../../utils/utils'

export const LOCKED_RESOURCE = 'plugin-server:locks:schedule'

export async function startSchedule(server: Hub, piscina: Piscina, onLock?: () => void): Promise<ScheduleControl> {
    status.info('⏰', 'Starting scheduling service...')

    let stopped = false
    let weHaveTheLock = false

    // Import this just to trigger build on ts-node-dev
    // This is a total hack and needs to be fixed - seems to be bug with ts-node-dev
    const _ = require('../../worker/worker')

    let pluginSchedulePromise = loadPluginSchedule(piscina)
    server.pluginSchedule = await pluginSchedulePromise

    const runEveryMinuteJob = schedule.scheduleJob('* * * * *', async () => {
        !stopped &&
            weHaveTheLock &&
            (await pluginSchedulePromise) &&
            runScheduleDebounced(server!, piscina!, 'runEveryMinute')
    })
    const runEveryHourJob = schedule.scheduleJob('0 * * * *', async () => {
        !stopped &&
            weHaveTheLock &&
            (await pluginSchedulePromise) &&
            runScheduleDebounced(server!, piscina!, 'runEveryHour')
    })
    const runEveryDayJob = schedule.scheduleJob('0 0 * * *', async () => {
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
        runEveryDayJob && schedule.cancelJob(runEveryDayJob)
        runEveryHourJob && schedule.cancelJob(runEveryHourJob)
        runEveryMinuteJob && schedule.cancelJob(runEveryMinuteJob)

        await unlock()
        await waitForTasksToFinish(server!)
    }

    const reloadSchedule = async () => {
        pluginSchedulePromise = loadPluginSchedule(piscina)
        server.pluginSchedule = await pluginSchedulePromise
    }

    return { stopSchedule, reloadSchedule }
}

export async function loadPluginSchedule(piscina: Piscina, maxIterations = 2000): Promise<Hub['pluginSchedule']> {
    // :TRICKY: While loadSchedule is called during the worker init process, it sometimes does not finish executing
    //  due to threading shenanigans. Nudge the plugin server to finish loading!
    void piscina.broadcastTask({ task: 'reloadSchedule' })
    while (maxIterations--) {
        const schedule = (await piscina.run({ task: 'getPluginSchedule' })) as Record<string, PluginConfigId[]> | null
        if (schedule) {
            return schedule
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
