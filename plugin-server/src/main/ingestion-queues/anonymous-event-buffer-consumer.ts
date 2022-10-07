import { PluginEvent } from '@posthog/plugin-scaffold'
import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka } from 'kafkajs'
import { KafkaProducerWrapper } from 'utils/db/kafka-producer-wrapper'

import { KAFKA_BUFFER, KAFKA_EVENTS_DEAD_LETTER_QUEUE } from '../../config/kafka-topics'
import { JobName } from '../../types'
import { status } from '../../utils/status'
import { GraphileQueue } from '../job-queues/concurrent/graphile-queue'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'

export const startAnonymousEventBufferConsumer = async ({
    kafka,
    producer,
    graphileQueue,
    statsd,
}: {
    kafka: Kafka
    producer: KafkaProducerWrapper
    graphileQueue: GraphileQueue
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
                eventPayload: eventPayload,
                timestamp: Number.parseInt(message.headers.processEventAt.toString()),
                jobKey: message.headers.eventId.toString(), // Ensure we don't create duplicates
            }

            status.debug('⬆️', 'Enqueuing anonymous event for processing', { job })

            await graphileQueue.enqueue(JobName.BUFFER_JOB, job)

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
