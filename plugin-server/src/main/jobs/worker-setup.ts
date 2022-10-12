import Piscina from '@posthog/piscina'
import { TaskList } from 'graphile-worker'

import { EnqueuedBufferJob, EnqueuedPluginJob, Hub, JobsConsumerControl } from '../../types'
import { killProcess } from '../../utils/kill'
import { status } from '../../utils/status'
import { logOrThrowJobQueueError } from '../../utils/utils'
import { pauseQueueIfWorkerFull } from '../ingestion-queues/queue'
import { runInstrumentedFunction } from '../utils'
import { runBufferEventPipeline } from './buffer'

export async function startGraphileWorker(hub: Hub, piscina: Piscina): Promise<JobsConsumerControl> {
    status.info('🔄', 'Starting Graphile Worker...')

    let jobHandlers: TaskList = {}

    if (hub.capabilities.ingestion) {
        jobHandlers = { ...jobHandlers, ...getIngestionJobHandlers(hub, piscina) }
        status.info('🔄', 'Graphile Worker: set up ingestion job handlers ...')
    }

    if (hub.capabilities.processPluginJobs) {
        jobHandlers = { ...jobHandlers, ...getPluginJobHandlers(hub, piscina) }
        status.info('🔄', 'Graphile Worker: set up plugin job handlers ...')
    }

    if (hub.capabilities.pluginScheduledTasks) {
        jobHandlers = { ...jobHandlers, ...getScheduledTaskHandlers() }
        status.info('🔄', 'Graphile Worker: set up scheduled task handlers ...')
    }

    try {
        await hub.graphileWorker.start(jobHandlers)
    } catch (error) {
        try {
            logOrThrowJobQueueError(hub, error, `Cannot start job queue consumer!`)
        } catch {
            killProcess()
        }
    }

    const stop = async () => {
        status.info('🔄', 'Stopping job queue consumer')
        await hub.graphileWorker.stop()
    }

    return { stop, resume: () => hub.graphileWorker.resumeConsumer() }
}

function getIngestionJobHandlers(hub: Hub, piscina: Piscina): TaskList {
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

function getPluginJobHandlers(hub: Hub, piscina: Piscina): TaskList {
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

function getScheduledTaskHandlers(): TaskList {
    const scheduledTaskHandlers: TaskList = {}

    return scheduledTaskHandlers
}
