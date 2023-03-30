import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka, Producer } from 'kafkajs'
import { Counter } from 'prom-client'
import { convertToIngestionEvent } from '../../utils/event'
import { AutomationManager } from '../../worker/automations/automation-manager'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { IngestionPersonData, RawClickHouseEvent } from '../../types'
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
    automationManager,
    statsd,
}: {
    kafka: Kafka
    producer: Producer // NOTE: not using KafkaProducerWrapper here to avoid buffering logic
    graphileWorker: GraphileWorker
    automationManager: AutomationManager
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
        status.debug('🔁', 'Processing automation batch', { size: batch.messages.length })
        for (const message of batch.messages) {
            if (!message.value) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    value: message.value,
                })

                resolveOffset(message.offset)
                continue
            }

            try {
                const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
                const event = convertToIngestionEvent(clickHouseEvent)
                await automationManager.startWithEvent(event, graphileWorker)
            } catch (error) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    error,
                })
                resolveOffset(message.offset)
                continue
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
