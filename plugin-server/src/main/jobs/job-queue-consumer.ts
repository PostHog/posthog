import Piscina from '@posthog/piscina'
import { TaskList } from 'graphile-worker'

import { EnqueuedBufferJob, EnqueuedPluginJob, Hub, JobQueueConsumerControl } from '../../types'
import { killProcess } from '../../utils/kill'
import { status } from '../../utils/status'
import { logOrThrowJobQueueError } from '../../utils/utils'
import { pauseQueueIfWorkerFull } from '../ingestion-queues/queue'
import { runInstrumentedFunction } from '../utils'
import { runBufferEventPipeline } from './buffer'

export async function startJobQueueConsumer(hub: Hub, piscina: Piscina): Promise<JobQueueConsumerControl> {
    status.info('🔄', 'Starting job queue consumer, trying to get lock...')

    const ingestionJobHandlers: TaskList = {
        bufferJob: async (job) => {
            pauseQueueIfWorkerFull(() => hub.jobQueueManager.pauseConsumer(), hub, piscina)
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

    const pluginJobHandlers: TaskList = {
        pluginJob: async (job) => {
            pauseQueueIfWorkerFull(() => hub.jobQueueManager.pauseConsumer(), hub, piscina)
            hub.statsd?.increment('triggered_job', {
                instanceId: hub.instanceId.toString(),
            })
            await piscina.run({ task: 'runPluginJob', args: { job: job as EnqueuedPluginJob } })
        },
    }

    const jobHandlers: TaskList = {
        ...(hub.capabilities.ingestion ? ingestionJobHandlers : {}),
        ...(hub.capabilities.processPluginJobs ? pluginJobHandlers : {}),
    }

    status.info('🔄', 'Job queue consumer starting')
    try {
        await hub.jobQueueManager.startConsumer(jobHandlers)
    } catch (error) {
        try {
            logOrThrowJobQueueError(hub, error, `Cannot start job queue consumer!`)
        } catch {
            killProcess()
        }
    }

    const stop = async () => {
        status.info('🔄', 'Stopping job queue consumer')
        await hub.jobQueueManager.stopConsumer()
    }

    return { stop, resume: () => hub.jobQueueManager.resumeConsumer() }
}
