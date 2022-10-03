import { PluginEvent } from '@posthog/plugin-scaffold'
import { Hub, JobName } from 'types'

export const startAnonymousEventBufferConsumer = (hub: Hub) => {
    const consumer = hub.kafka.consumer({ groupId: 'clickhouse-ingester' })
    consumer.run({
        eachBatch: async ({ batch }) => {
            for (const message of batch.messages) {
                if (!message.value || !message.headers?.processEventAt) {
                    continue
                }

                const job = {
                    eventPayload: JSON.parse(message.value.toString()) as PluginEvent,
                    timestamp: Number.parseInt(message.headers.processEventAt.toString()),
                }

                await hub.jobQueueManager.enqueue(JobName.BUFFER_JOB, job)
            }
        },
    })

    return consumer
}
