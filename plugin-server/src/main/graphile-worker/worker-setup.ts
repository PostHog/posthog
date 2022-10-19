import { CronItem, TaskList } from 'graphile-worker'

import { EnqueuedPluginJob, Hub } from '../../types'
import { status } from '../../utils/status'
import { workerTasks } from '../../worker/tasks'
import { pauseQueueIfWorkerFull } from '../ingestion-queues/queue'
import { GraphileWorker } from './graphile-worker'
import { loadPluginSchedule, runScheduledTasks } from './schedule'

export async function startGraphileWorker(hub: Hub, graphileWorker: GraphileWorker) {
    status.info('🔄', 'Starting Graphile Worker...')

    let jobHandlers: TaskList = {}

    const crontab: CronItem[] = []

    if (hub.capabilities.processPluginJobs) {
        jobHandlers = { ...jobHandlers, ...getPluginJobHandlers(hub, graphileWorker) }
        status.info('🔄', 'Graphile Worker: set up plugin job handlers ...')
    }

    if (hub.capabilities.pluginScheduledTasks) {
        hub.pluginSchedule = await loadPluginSchedule(hub)

        // TODO: In the future we might benefit from scheduling tasks more granularly i.e. <taskType, pluginConfigId>
        // KLUDGE: Given we're currently not doing the above, if we throw after executing n tasks for given type, those n tasks will be re-run
        // Note: backfillPeriod must be explicitly defined here (without passing options it defaults to 0 anyway) but we'd currently
        // not like to use it as it has a lot of limitations (see: https://github.com/graphile/worker#limiting-backfill)
        // We might benefit from changing this setting in the future
        crontab.push({
            task: 'runEveryMinute',
            identifier: 'runEveryMinute',
            pattern: '* * * * *',
            options: { maxAttempts: 1, backfillPeriod: 0 },
        })
        crontab.push({
            task: 'runEveryHour',
            identifier: 'runEveryHour',
            pattern: '0 * * * *',
            options: { maxAttempts: 5, backfillPeriod: 0 },
        })
        crontab.push({
            task: 'runEveryDay',
            identifier: 'runEveryDay',
            pattern: '0 0 * * *',
            options: { maxAttempts: 10, backfillPeriod: 0 },
        })

        jobHandlers = {
            ...jobHandlers,
            ...getScheduledTaskHandlers(hub),
        }

        status.info('🔄', 'Graphile Worker: set up scheduled task handlers...')
    }

    await graphileWorker.start(jobHandlers, crontab)
    return graphileWorker
}

export function getPluginJobHandlers(hub: Hub, graphileWorker: GraphileWorker): TaskList {
    const pluginJobHandlers: TaskList = {
        pluginJob: async (job) => {
            pauseQueueIfWorkerFull(() => graphileWorker.pause(), hub)
            hub.statsd?.increment('triggered_job', {
                instanceId: hub.instanceId.toString(),
            })
            await workerTasks['runPluginJob'](hub, { job: job as EnqueuedPluginJob })
        },
    }

    return pluginJobHandlers
}

export function getScheduledTaskHandlers(hub: Hub): TaskList {
    const scheduledTaskHandlers: TaskList = {
        runEveryMinute: async () => await runScheduledTasks(hub, 'runEveryMinute'),
        runEveryHour: async () => await runScheduledTasks(hub, 'runEveryHour'),
        runEveryDay: async () => await runScheduledTasks(hub, 'runEveryDay'),
    }

    return scheduledTaskHandlers
}
