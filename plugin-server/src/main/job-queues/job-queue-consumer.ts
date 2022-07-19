import Piscina from '@posthog/piscina'
import { TaskList } from 'graphile-worker'

import { EnqueuedJob, Hub, JobQueueConsumerControl } from '../../types'
import { killProcess } from '../../utils/kill'
import { status } from '../../utils/status'
import { logOrThrowJobQueueError } from '../../utils/utils'
import { pauseQueueIfWorkerFull } from '../ingestion-queues/queue'

export async function startJobQueueConsumer(server: Hub, piscina: Piscina): Promise<JobQueueConsumerControl> {
    status.info('🔄', 'Starting job queue consumer, trying to get lock...')

    const jobHandlers: TaskList = {
        pluginJob: async (job) => {
            pauseQueueIfWorkerFull(() => server.jobQueueManager.pauseConsumer(), server, piscina)
            server.statsd?.increment('triggered_job', {
                instanceId: server.instanceId.toString(),
            })
            await piscina.run({ task: 'runJob', args: { job: job as EnqueuedJob } })
        },
    }

    status.info('🔄', 'Job queue consumer starting')
    try {
        await server.jobQueueManager.startConsumer(jobHandlers)
    } catch (error) {
        try {
            logOrThrowJobQueueError(server, error, `Cannot start job queue consumer!`)
        } catch {
            killProcess()
        }
    }

    const stop = async () => {
        status.info('🔄', 'Stopping job queue consumer')
        await server.jobQueueManager.stopConsumer()
    }

    return { stop, resume: () => server.jobQueueManager.resumeConsumer() }
}
