import Piscina from '@posthog/piscina'
import { TaskList } from 'graphile-worker'

import { EnqueuedBufferJob, EnqueuedPluginJob, Hub } from '../../types'
import { pauseQueueIfWorkerFull } from '../ingestion-queues/queue'
import { runInstrumentedFunction } from '../utils'
import { runBufferEventPipeline } from './buffer'
import { runScheduledTasks } from './schedule'

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
        runEveryMinute: async () => await runScheduledTasks(hub, piscina, 'runEveryMinute'),
        runEveryHour: async () => await runScheduledTasks(hub, piscina, 'runEveryHour'),
        runEveryDay: async () => await runScheduledTasks(hub, piscina, 'runEveryDay'),
    }

    return scheduledTaskHandlers
}
