import { PluginEvent } from '@posthog/plugin-scaffold'
import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka } from 'kafkajs'
import { JobQueueManager } from 'main/job-queues/job-queue-manager'
import { KafkaProducerWrapper } from 'utils/db/kafka-producer-wrapper'

import { KAFKA_BUFFER, KAFKA_EVENTS_DEAD_LETTER_QUEUE } from '../../config/kafka-topics'
import { JobName } from '../../types'
import { status } from '../../utils/status'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'

export const startAnonymousEventBufferConsumer = async ({
    kafka,
    producer,
    jobQueueManager,
    statsd,
}: {
    kafka: Kafka
    producer: KafkaProducerWrapper
    jobQueueManager: JobQueueManager
    statsd?: StatsD
}) => {
    /*
        Consumes from the anonymous event topic, and enqueues the events for
        processing at a later date as per the message header `processEventAt`.

        We do this delayed processing to allow for the anonymous users that
        these events are associated to be merged or identified as other
        "identified" users, at which point to can denormalize data to improve
        query performance.

        On failure to enqueue we will fail the batch. only on successfully
        enqueuing an entire batch to Graphile Worker (a PostgreSQL backed async
        worker library).

        TODO:

        1. distinguish between operational errors and programming errors
        2. ensure offset only updated if message pushed to DLQ
    */

    const consumer = kafka.consumer({ groupId: 'ingester' })
    setupEventHandlers(consumer)

    status.info('🔁', 'Starting anonymous event buffer consumer')

    const eachBatch: EachBatchHandler = async ({ batch, resolveOffset, heartbeat }) => {
        status.info('🔁', 'Processing batch', { size: batch.messages.length })
        for (const message of batch.messages) {
            if (!message.value || !message.headers?.processEventAt || !message.headers?.eventId) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    value: message.value,
                    processEventAt: message.headers?.processEventAt,
                    eventId: message.headers?.eventId,
                })
                producer.queueMessage({ topic: KAFKA_EVENTS_DEAD_LETTER_QUEUE, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            let eventPayload: PluginEvent

            try {
                eventPayload = JSON.parse(message.value.toString())
            } catch (error) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    error,
                })
                producer.queueMessage({ topic: KAFKA_EVENTS_DEAD_LETTER_QUEUE, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            const job = {
                jobKey: message.headers.eventId.toString(), // Ensure we don't create duplicates
                eventPayload: eventPayload,
                timestamp: Number.parseInt(message.headers.processEventAt.toString()),
            }

            status.debug('⬆️', 'Enqueuing anonymous event for processing', { job })

            // NOTE: `jobQueueManager.enqueue` handles retries internally.
            // As such this can take a long time, so we need to ensure we
            // keep the heartbeat going during this time, every 5 seconds.
            // NOTE: it might be worth handling retry logic explicit here so
            // get better control on which errors we retry on.
            const heartbeatTimer = setInterval(async () => await heartbeat(), 5000)
            await jobQueueManager.enqueue(JobName.BUFFER_JOB, job)
            clearTimeout(heartbeatTimer)

            // Resolve the offset such that, in case of errors further in
            // the batch, we will not process these again
            resolveOffset(message.offset)

            // After processing every message we keep a heartbeat going to ensure we don't
            // get kicked out of the consumer group.
            await heartbeat()

            status.info('✅', 'Processed batch', { size: batch.messages.length })
        }
    }

    await consumer.connect()
    await consumer.subscribe({ topic: KAFKA_BUFFER })
    await consumer.run({
        eachBatch: async (payload) => {
            return await instrumentEachBatch(KAFKA_BUFFER, eachBatch, payload, statsd)
        },
    })

    return consumer
}
