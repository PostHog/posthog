import Piscina from '@posthog/piscina'

import { Hub, JobQueueConsumerControl, OnJobCallback } from '../../types'
import { status } from '../../utils/status'
import { pauseQueueIfWorkerFull } from '../ingestion-queues/queue'

export async function startJobQueueConsumer(server: Hub, piscina: Piscina): Promise<JobQueueConsumerControl> {
    status.info('🔄', 'Starting job queue consumer, trying to get lock...')

    const onJob: OnJobCallback = async (jobs) => {
        pauseQueueIfWorkerFull(() => server.jobQueueManager.pauseConsumer(), server, piscina)
        for (const job of jobs) {
            server.statsd?.increment('triggered_job', {
                instanceId: server.instanceId.toString(),
            })
            await piscina.run({ task: 'runJob', args: { job } })
        }
    }

    await server.jobQueueManager.startConsumer(onJob)

    const stop = async () => {
        status.info('🔄', 'Stopping job queue consumer')
        await server.jobQueueManager.stopConsumer()
    }

    return { stop, resume: () => server.jobQueueManager.resumeConsumer() }
}
