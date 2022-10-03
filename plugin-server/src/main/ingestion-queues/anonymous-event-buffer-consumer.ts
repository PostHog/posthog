import { PluginEvent } from '@posthog/plugin-scaffold'
import { Kafka } from 'kafkajs'
import { JobQueueManager } from 'main/job-queues/job-queue-manager'

import { JobName } from '../../types'

export const startAnonymousEventBufferConsumer = (kafka: Kafka, jobQueueManager: JobQueueManager) => {
    const consumer = kafka.consumer({ groupId: 'clickhouse-ingester' })

    void consumer.run({
        eachBatch: async ({ batch }) => {
            for (const message of batch.messages) {
                if (!message.value || !message.headers?.processEventAt) {
                    continue
                }

                const job = {
                    eventPayload: JSON.parse(message.value.toString()) as PluginEvent,
                    timestamp: Number.parseInt(message.headers.processEventAt.toString()),
                }

                await jobQueueManager.enqueue(JobName.BUFFER_JOB, job)
            }
        },
    })

    return consumer
}
