import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka } from 'kafkajs'
import { KafkaProducerWrapper } from 'utils/db/kafka-producer-wrapper'

import { KAFKA_EVENTS_DEAD_LETTER_QUEUE, KAFKA_JOBS } from '../../config/kafka-topics'
import { EnqueuedPluginJob, JobName } from '../../types'
import { status } from '../../utils/status'
import { GraphileWorker } from '../graphile-worker/graphile-worker'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'

export const startJobsConsumer = async ({
    kafka,
    producer,
    graphileWorker,
    statsd,
}: {
    kafka: Kafka
    producer: KafkaProducerWrapper
    graphileWorker: GraphileWorker
    statsd?: StatsD
}) => {
    /*
        Consumes from the jobs buffer topic, and enqueues the jobs for execution
        at a later date.
    */

    const consumer = kafka.consumer({ groupId: 'jobs-inserter' })
    setupEventHandlers(consumer)

    status.info('🔁', 'Starting jobs consumer')

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

            let job: EnqueuedPluginJob

            try {
                job = JSON.parse(message.value.toString())
            } catch (error) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    error,
                })
                producer.queueMessage({ topic: KAFKA_EVENTS_DEAD_LETTER_QUEUE, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            status.debug('⬆️', 'Enqueuing plugin job', { job })
            try {
                await graphileWorker.enqueue(JobName.PLUGIN_JOB, job)
                statsd?.increment('jobs_consumer.enqueued')
            } catch (error) {
                status.error('⚠️', 'Failed to enqueue anonymous event for processing', { error })
                statsd?.increment('jobs_consumer.enqueue_error')
                throw error
            }

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
    await consumer.subscribe({ topic: KAFKA_JOBS })
    await consumer.run({
        eachBatch: async (payload) => {
            return await instrumentEachBatch(KAFKA_JOBS, eachBatch, payload, statsd)
        },
    })

    return consumer
}
