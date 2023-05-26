import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka } from 'kafkajs'
import { Counter } from 'prom-client'
import { KafkaProducerWrapper } from 'utils/db/kafka-producer-wrapper'

import { KAFKA_JOBS, KAFKA_JOBS_DLQ } from '../../config/kafka-topics'
import { EnqueuedPluginJob, JobName } from '../../types'
import { status } from '../../utils/status'
import { GraphileWorker } from '../graphile-worker/graphile-worker'
import { instrumentEachBatchKafkaJS, setupEventHandlers } from './kafka-queue'
import { latestOffsetTimestampGauge } from './metrics'

const jobsConsumerSuccessCounter = new Counter({
    name: 'jobs_consumer_enqueue_success_total',
    help: 'Number of jobs successfully enqueued to Graphile from the Kafka buffer.',
})

const jobsConsumerFailuresCounter = new Counter({
    name: 'jobs_consumer_enqueue_failures_total',
    help: 'Number of Graphile errors while enqueuing jobs from the Kafka buffer.',
})

export const startJobsConsumer = async ({
    kafka,
    producer,
    graphileWorker,
    statsd,
    skipPluginConfigIds,
}: {
    kafka: Kafka
    producer: KafkaProducerWrapper
    graphileWorker: GraphileWorker
    statsd?: StatsD
    skipPluginConfigIds: string
}) => {
    /*
        Consumes from the jobs buffer topic, and enqueues the jobs for execution
        at a later date.
    */

    const groupId = 'jobs-inserter'
    const consumer = kafka.consumer({ groupId })
    setupEventHandlers(consumer)

    const skippedPluginConfigIds = skipPluginConfigIds.split(',')

    status.info('🔁', 'Starting jobs consumer', {
        skippedPluginConfigIds: skippedPluginConfigIds,
    })

    const eachBatch: EachBatchHandler = async ({ batch, resolveOffset, heartbeat, commitOffsetsIfNecessary }) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })
        for (const message of batch.messages) {
            if (!message.value) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    value: message.value,
                })
                // TODO: handle resolving offsets asynchronously
                await producer.queueMessage({
                    topic: KAFKA_JOBS_DLQ,
                    messages: [{ value: message.value, key: message.key }],
                })
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
                await producer.queueMessage({
                    topic: KAFKA_JOBS_DLQ,
                    messages: [{ value: message.value, key: message.key }],
                })
                resolveOffset(message.offset)
                continue
            }

            if (skippedPluginConfigIds.includes(job.pluginConfigId.toString())) {
                status.info('⬆️', 'Skipping plugin job because of config', {
                    type: job.type,
                    pluginConfigId: job.pluginConfigId,
                    pluginConfigTeam: job.pluginConfigTeam,
                })
                statsd?.increment('jobs_consumer.skipped')
                tasksDroppedCounter.inc()
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
                jobsConsumerSuccessCounter.inc()
                statsd?.increment('jobs_consumer.enqueued')
                tasksQueuedCounter.inc()
            } catch (error) {
                status.error('⚠️', 'Failed to enqueue anonymous event for processing', { error })
                jobsConsumerFailuresCounter.inc()
                statsd?.increment('jobs_consumer.enqueue_error')
                tasksQueueErrorsCounter.inc()
                throw error
            }

            // After processing each message, we need to heartbeat to ensure
            // we don't get kicked out of the group. Note that although we call
            // this for each message, it's actually a no-op if we're not over
            // the heartbeatInterval.
            await heartbeat()
        }

        await commitOffsetsIfNecessary()

        const lastBatchMessage = batch.messages[batch.messages.length - 1]
        latestOffsetTimestampGauge
            .labels({ partition: batch.partition, topic: batch.topic, groupId })
            .set(Number.parseInt(lastBatchMessage.timestamp))

        status.debug('✅', 'Processed batch', { size: batch.messages.length })
    }

    await consumer.connect()
    await consumer.subscribe({ topic: KAFKA_JOBS })
    await consumer.run({
        eachBatch: async (payload) => {
            return await instrumentEachBatchKafkaJS(KAFKA_JOBS, eachBatch, payload, statsd)
        },
    })

    return {
        ...consumer,
        stop: async () => {
            await consumer.stop()
        },
    }
}

const tasksQueuedCounter = new Counter({
    name: 'jobs_consumer_tasks_queued_total',
    help: 'Count of tasks queued into graphile by the job consumer.',
})

const tasksQueueErrorsCounter = new Counter({
    name: 'jobs_consumer_tasks_queue_errors_total',
    help: 'Count of errors trying to queue into graphile.',
})
const tasksDroppedCounter = new Counter({
    name: 'jobs_consumer_tasks_dropped_total',
    help: 'Count of tasks dropped by the job consumer because of pluginconfig ID filtering.',
})
