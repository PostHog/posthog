import Piscina from '@posthog/piscina'
import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka, Producer } from 'kafkajs'

import { KAFKA_SCHEDULED_TASKS, KAFKA_SCHEDULED_TASKS_DLQ } from '../../config/kafka-topics'
import { status } from '../../utils/status'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'

export const startScheduledTasksConsumer = async ({
    kafka,
    piscina,
    producer,
    statsd,
}: {
    kafka: Kafka
    piscina: Piscina
    producer: Producer // NOTE: not using KafkaProducerWrapper here to avoid buffering logic
    statsd?: StatsD
}) => {
    /*
        Consumes from the tasks buffer topic, and enqueues the tasks for execution
        at a later date.
    */

    const consumer = kafka.consumer({ groupId: 'scheduled-tasks-runner' })
    setupEventHandlers(consumer)

    status.info('🔁', 'Starting scheduled tasks consumer')

    const eachBatch: EachBatchHandler = async ({ batch, resolveOffset, heartbeat }) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })
        for (const message of batch.messages) {
            if (!message.value) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    value: message.value,
                })
                // TODO: handle resolving offsets asynchronously
                await producer.send({ topic: KAFKA_SCHEDULED_TASKS_DLQ, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            let task: {
                taskType: 'runEveryMinute' | 'runEveryHour' | 'runEveryDay'
                pluginConfigId: number
            }

            try {
                task = JSON.parse(message.value.toString())
            } catch (error) {
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    error,
                })
                // TODO: handle resolving offsets asynchronously
                await producer.send({ topic: KAFKA_SCHEDULED_TASKS_DLQ, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            status.debug('⬆️', 'Running scheduled task', {
                task,
            })

            try {
                await piscina.run({ task: task.taskType, args: { pluginConfigId: task.pluginConfigId } })
                resolveOffset(message.offset)
                statsd?.increment('tasks_consumer.enqueued')
            } catch (error) {
                status.error('⚠️', 'Failed to enqueue anonymous event for processing', { error })
                statsd?.increment('tasks_consumer.enqueue_error')
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
    await consumer.subscribe({ topic: KAFKA_SCHEDULED_TASKS })
    await consumer.run({
        eachBatch: async (payload) => {
            return await instrumentEachBatch(KAFKA_SCHEDULED_TASKS, eachBatch, payload, statsd)
        },
    })

    return consumer
}
