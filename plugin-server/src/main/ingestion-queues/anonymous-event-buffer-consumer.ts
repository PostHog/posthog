import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka } from 'kafkajs'

import { KAFKA_BUFFER, KAFKA_EVENTS_DEAD_LETTER_QUEUE } from '../../config/kafka-topics'
import { runBufferEventPipeline } from '../../main/graphile-worker/buffer'
import { Hub } from '../../types'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import { status } from '../../utils/status'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'

export const startAnonymousEventBufferConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
    piscina,
    kafka,
    producer,
    statsd,
}: {
    hub: Hub
    piscina: Piscina
    kafka: Kafka
    producer: KafkaProducerWrapper
    statsd?: StatsD
}) => {
    /*
        Consumes from the anonymous event topic, and enqueues the events for
        processing at a later date as per the message header `processEventAt`.

        We do this delayed processing to allow for the anonymous users that
        these events are associated to be merged or identified as other
        "identified" users, at which point to can denormalize data to improve
        query performance.

        On failure to enqueue to Graphile Worker, we will fail the eachBatch
        call resulting in KafkaJS rety mechanism kicking in. Any messages that
        we have called `resolveOffset` KafkaJS will try to set offsets for.

        TODO:

        1. distinguish between operational errors and programming errors
        2. ensure offset only updated if message pushed to DLQ
    */

    const consumer = kafka.consumer({ groupId: 'ingester' })
    setupEventHandlers(consumer)

    status.info('🔁', 'Starting anonymous event buffer consumer')

    const eachBatch: EachBatchHandler = async ({ batch, resolveOffset, heartbeat, pause }) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })
        for (const message of batch.messages) {
            if (!message.value || !message.headers?.processEventAt || !message.headers?.eventId) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    value: message.value,
                    processEventAt: message.headers?.processEventAt,
                    eventId: message.headers?.eventId,
                })
                await producer.queueMessage({ topic: KAFKA_EVENTS_DEAD_LETTER_QUEUE, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            const processEventAt = Number.parseInt(message.headers.processEventAt.toString())
            const now = Date.now()
            if (processEventAt > now) {
                const eventId = message.headers.eventId.toString()
                status.info('🔁', 'Delaying event processing', {
                    topic: batch.topic,
                    partition: batch.partition,
                    eventId: eventId,
                    delayMs: processEventAt - now,
                    processEventAt,
                    now,
                })
                const resume = pause()
                setTimeout(() => {
                    status.info('🔁', 'Resuming event processing', {
                        topic: batch.topic,
                        partition: batch.partition,
                        eventId: eventId,
                        delayMs: processEventAt - now,
                    })
                    resume()
                }, processEventAt - now)

                return
            }

            let eventPayload: PluginEvent

            try {
                eventPayload = JSON.parse(message.value.toString())
            } catch (error) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    error,
                })
                await producer.queueMessage({ topic: KAFKA_EVENTS_DEAD_LETTER_QUEUE, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            status.debug('⬆️', 'Processing anonymous event', { eventId: message.headers.eventId.toString() })
            await runBufferEventPipeline(hub, piscina, eventPayload)
            resolveOffset(message.offset)

            // After processing each message, we need to heartbeat to ensure
            // we don't get kicked out of the group. Note that although we call
            // this for each message, it's actually a no-op if we're not over
            // the heartbeatInterval.
            await heartbeat()
        }

        status.info('✅', 'Processed batch', { size: batch.messages.length })
    }

    await consumer.connect()
    await consumer.subscribe({ topic: KAFKA_BUFFER })
    await consumer.run({
        eachBatchAutoResolve: false,
        eachBatch: async (payload) => {
            return await instrumentEachBatch(KAFKA_BUFFER, eachBatch, payload, statsd)
        },
    })

    return consumer
}
