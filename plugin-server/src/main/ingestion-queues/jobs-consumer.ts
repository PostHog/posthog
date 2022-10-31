import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka, Producer } from 'kafkajs'

import { KAFKA_JOBS, KAFKA_JOBS_DLQ } from '../../config/kafka-topics'
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
    producer: Producer // NOTE: not using KafkaProducerWrapper here to avoid buffering logic
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
            if (!message.value) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    value: message.value,
                })
                // TODO: handle resolving offsets asynchronously
                await producer.send({ topic: KAFKA_JOBS_DLQ, messages: [message] })
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
                // TODO: handle resolving offsets asynchronously
                await producer.send({ topic: KAFKA_JOBS_DLQ, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            status.debug('⬆️', 'Enqueuing plugin job', {
                type: job.type,
                pluginConfigId: job.pluginConfigId,
                pluginConfigTeam: job.pluginConfigTeam,
            })

            try {
                await graphileWorker.enqueue(JobName.PLUGIN_JOB, job)
                resolveOffset(message.offset)
                statsd?.increment('jobs_consumer.enqueued')
            } catch (error) {
                status.error('⚠️', 'Failed to enqueue anonymous event for processing', { error })
                statsd?.increment('jobs_consumer.enqueue_error')
                throw error
            }

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
