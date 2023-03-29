import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka, Producer } from 'kafkajs'
import { Counter } from 'prom-client'

import { KAFKA_EVENTS_JSON, KAFKA_JOBS_DLQ } from '../../config/kafka-topics'
import { EnqueuedAutomationJob, JobName } from '../../types'
import { status } from '../../utils/status'
import { GraphileWorker } from '../graphile-worker/graphile-worker'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'
import { latestOffsetTimestampGauge } from './metrics'

const jobsConsumerSuccessCounter = new Counter({
    name: 'automations_consumer_enqueue_success_total',
    help: 'Number of automations successfully enqueued to Graphile from Kafka.',
})

const jobsConsumerFailuresCounter = new Counter({
    name: 'automations_consumer_enqueue_failures_total',
    help: 'Number of Graphile errors while enqueuing automations from Kafka.',
})

export const startAutomationsConsumer = async ({
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
        Consumes from the incoming events and determines if an automation should be started or not.
    */

    const groupId = 'automation-starter'
    const consumer = kafka.consumer({ groupId })
    setupEventHandlers(consumer)

    status.info('🔁', 'Starting automations starter')

    const eachBatch: EachBatchHandler = async ({ batch, resolveOffset, heartbeat, commitOffsetsIfNecessary }) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })
        for (const message of batch.messages) {
            // 1. Ensure we have the loaded automations from the DB
            // 2. Iterate over them and check if the event matches any of them

            // if (!message.value) {
            //     status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
            //         value: message.value,
            //     })
            //     // TODO: handle resolving offsets asynchronously
            //     await producer.send({ topic: KAFKA_JOBS_DLQ, messages: [message] })
            //     resolveOffset(message.offset)
            //     continue
            // }

            // let job: EnqueuedAutomationJob

            // try {
            //     job = JSON.parse(message.value.toString())
            // } catch (error) {
            //     status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
            //         error,
            //     })
            //     // TODO: handle resolving offsets asynchronously
            //     await producer.send({ topic: KAFKA_JOBS_DLQ, messages: [message] })
            //     resolveOffset(message.offset)
            //     continue
            // }

            // status.debug('⬆️', 'Enqueuing plugin job', {
            //     type: job.type,
            //     pluginConfigId: job.pluginConfigId,
            //     pluginConfigTeam: job.pluginConfigTeam,
            // })

            // try {
            //     await graphileWorker.enqueue(JobName.AUTOMATION_JOB, job)
            //     jobsConsumerSuccessCounter.inc()
            //     statsd?.increment('automations_consumer.enqueued')
            // } catch (error) {
            //     status.error('⚠️', 'Failed to enqueue anonymous event for processing', { error })
            //     jobsConsumerFailuresCounter.inc()
            //     statsd?.increment('automations_consumer.enqueue_error')

            //     throw error
            // }

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

        status.debug('✅', 'Processed automation batch', { size: batch.messages.length })
    }

    await consumer.connect()
    await consumer.subscribe({ topic: KAFKA_EVENTS_JSON })
    await consumer.run({
        eachBatch: async (payload) => {
            return await instrumentEachBatch(KAFKA_EVENTS_JSON, eachBatch, payload, statsd)
        },
    })

    return consumer
}
