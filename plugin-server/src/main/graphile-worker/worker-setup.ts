import { CronItem, TaskList } from 'graphile-worker'

import { EnqueuedBufferJob, EnqueuedPluginJob, Hub } from '../../types'
import { status } from '../../utils/status'
import { workerTasks } from '../../worker/tasks'
import { pauseQueueIfWorkerFull } from '../ingestion-queues/queue'
import { runInstrumentedFunction } from '../utils'
import { runBufferEventPipeline } from './buffer'
import { loadPluginSchedule, runScheduledTasks } from './schedule'

export async function startGraphileWorker(hub: Hub): Promise<Error | undefined> {
    status.info('🔄', 'Starting Graphile Worker...')

    let jobHandlers: TaskList = {}

    const crontab: CronItem[] = []

    if (hub.capabilities.ingestion) {
        jobHandlers = { ...jobHandlers, ...getIngestionJobHandlers(hub) }
        status.info('🔄', 'Graphile Worker: set up ingestion job handlers ...')
    }

    if (hub.capabilities.processPluginJobs) {
        jobHandlers = { ...jobHandlers, ...getPluginJobHandlers(hub) }
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

    try {
        await hub.graphileWorker.start(jobHandlers, crontab)
    } catch (error) {
        return error
    }
}

export function getIngestionJobHandlers(hub: Hub): TaskList {
    const ingestionJobHandlers: TaskList = {
        bufferJob: async (job) => {
            pauseQueueIfWorkerFull(() => hub.graphileWorker.pause(), hub)
            const eventPayload = (job as EnqueuedBufferJob).eventPayload
            await runInstrumentedFunction({
                server: hub,
                event: eventPayload,
                func: () => runBufferEventPipeline(hub, eventPayload),
                statsKey: `kafka_queue.ingest_buffer_event`,
                timeoutMessage: 'After 30 seconds still running runBufferEventPipeline',
            })
            hub.statsd?.increment('events_deleted_from_buffer')
        },
    }

    return ingestionJobHandlers
}

export function getPluginJobHandlers(hub: Hub): TaskList {
    const pluginJobHandlers: TaskList = {
        pluginJob: async (job) => {
            pauseQueueIfWorkerFull(() => hub.graphileWorker.pause(), hub)
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
