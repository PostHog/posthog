import Piscina from '@posthog/piscina'
import { CronItem, TaskList } from 'graphile-worker'

import { EnqueuedBufferJob, EnqueuedPluginJob, EnqueuedScheduledTaskJob, Hub } from '../../types'
import { status } from '../../utils/status'
import { pauseQueueIfWorkerFull } from '../ingestion-queues/queue'
import { runInstrumentedFunction } from '../utils'
import { runBufferEventPipeline } from './buffer'
import { loadPluginSchedule, runScheduledTasks } from './schedule'

export async function startGraphileWorker(hub: Hub, piscina: Piscina): Promise<Error | undefined> {
    status.info('🔄', 'Starting Graphile Worker...')

    let jobHandlers: TaskList = {}

    const crontab: CronItem[] = []

    if (hub.capabilities.ingestion) {
        jobHandlers = { ...jobHandlers, ...getIngestionJobHandlers(hub, piscina) }
        status.info('🔄', 'Graphile Worker: set up ingestion job handlers ...')
    }

    if (hub.capabilities.processPluginJobs) {
        jobHandlers = { ...jobHandlers, ...getPluginJobHandlers(hub, piscina) }
        status.info('🔄', 'Graphile Worker: set up plugin job handlers ...')
    }

    if (hub.capabilities.pluginScheduledTasks) {
        hub.pluginSchedule = await loadPluginSchedule(piscina)

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
            ...getScheduledTaskHandlers(hub, piscina),
        }

        status.info('🔄', 'Graphile Worker: set up scheduled task handlers...')
    }

    try {
        await hub.graphileWorker.start(jobHandlers, crontab)
    } catch (error) {
        return error
    }
}

export function getIngestionJobHandlers(hub: Hub, piscina: Piscina): TaskList {
    const ingestionJobHandlers: TaskList = {
        bufferJob: async (job) => {
            pauseQueueIfWorkerFull(() => hub.graphileWorker.pause(), hub, piscina)
            const eventPayload = (job as EnqueuedBufferJob).eventPayload
            await runInstrumentedFunction({
                server: hub,
                event: eventPayload,
                func: () => runBufferEventPipeline(hub, piscina, eventPayload),
                statsKey: `kafka_queue.ingest_buffer_event`,
                timeoutMessage: 'After 30 seconds still running runBufferEventPipeline',
            })
            hub.statsd?.increment('events_deleted_from_buffer')
        },
    }

    return ingestionJobHandlers
}

export function getPluginJobHandlers(hub: Hub, piscina: Piscina): TaskList {
    const pluginJobHandlers: TaskList = {
        pluginJob: async (job) => {
            pauseQueueIfWorkerFull(() => hub.graphileWorker.pause(), hub, piscina)
            hub.statsd?.increment('triggered_job', {
                instanceId: hub.instanceId.toString(),
            })
            await piscina.run({ task: 'runPluginJob', args: { job: job as EnqueuedPluginJob } })
        },
    }

    return pluginJobHandlers
}

export function getScheduledTaskHandlers(hub: Hub, piscina: Piscina): TaskList {
    const scheduledTaskHandlers: TaskList = {
        runEveryMinute: async () => await runScheduledTasks(hub, 'runEveryMinute'),
        runEveryHour: async () => await runScheduledTasks(hub, 'runEveryHour'),
        runEveryDay: async () => await runScheduledTasks(hub, 'runEveryDay'),
        pluginScheduledTask: async (job) => {
            const task = (job as EnqueuedScheduledTaskJob).task
            const pluginConfigId = (job as EnqueuedScheduledTaskJob).pluginConfigId

            status.info('⏲️', `Running ${task} for plugin config with ID ${pluginConfigId}`)

            await piscina.run({
                task,
                args: { pluginConfigId },
            })
        },
    }

    return scheduledTaskHandlers
}
