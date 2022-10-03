import { PluginEvent } from '@posthog/plugin-scaffold'
import { Kafka } from 'kafkajs'
import { JobQueueManager } from 'main/job-queues/job-queue-manager'

import { JobName } from '../../types'

export const startAnonymousEventBufferConsumer = (kafka: Kafka, jobQueueManager: JobQueueManager) => {
    /*
        Consumes from the anonymous event topic, and enqueues the events for
        processing at a later date as per the message header `processEventAt`.

        We do this delayed processing to allow for the anonymous users that
        these events are assosiated to be merged or identified as other
        "identified" users, at which point to can denormalize data to improve
        query performance.

        On failure to enqueue we will fail the batch. only on successfully
        enqueuing an entire batch to Graphile Worker (a PostgreSQL backed async
        worker library).

        TODO:

        1. handle unhandled exceptions behaviour. At the moment we will end up 
           with an unhandled exception and I think the consumer will just stop.
        2. catch deserialization errors and send to Dead Letter Queue.
        3. catch Graphile Worker errors and send to Dead Letter Queue on all 
           but PostgreSQL availability errors.
    */

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
