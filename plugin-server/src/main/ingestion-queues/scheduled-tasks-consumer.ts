import Piscina from '@posthog/piscina'
import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka, Producer } from 'kafkajs'

import { KAFKA_SCHEDULED_TASKS, KAFKA_SCHEDULED_TASKS_DLQ } from '../../config/kafka-topics'
import { DependencyUnavailableError } from '../../utils/db/error'
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
        Consumes from the scheduled tasks topic, and executes them within a
        Piscina worker.
    */

    const consumer = kafka.consumer({ groupId: 'scheduled-tasks-runner' })
    setupEventHandlers(consumer)

    status.info('🔁', 'Starting scheduled tasks consumer')

    const eachBatch: EachBatchHandler = async ({ batch, resolveOffset, heartbeat }) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })
        for (const message of batch.messages) {
            if (!message.value) {
                status.error('⚠️', 'asdf', { topic: 'zxcv' })
                status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                    value: message.value,
                })
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
                    error: error.stack ?? error,
                })
                await producer.send({ topic: KAFKA_SCHEDULED_TASKS_DLQ, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            status.debug('⬆️', 'Running scheduled task', task)

            try {
                await piscina.run({ task: task.taskType, args: { pluginConfigId: task.pluginConfigId } })
                resolveOffset(message.offset)
                statsd?.increment('scheduled_tasks.success', { taskType: task.taskType })
            } catch (error) {
                if (error instanceof DependencyUnavailableError) {
                    // For errors relating to PostHog dependencies that are unavailable,
                    // e.g. Postgres, Kafka, Redis, we don't want to log the error to Sentry
                    // but rather bubble this up the stack for someone else to decide on
                    // what to do with it.
                    status.warn('⚠️', `Dependency unavailable for scheduled task`, {
                        pluginConfigId: task.pluginConfigId,
                    })
                    statsd?.increment('scheduled_tasks.retriable', { taskType: task.taskType })
                    throw error
                }

                status.error('⚠️', 'Failed to run scheduled task', { error: error.stack ?? error })
                statsd?.increment('scheduled_tasks.failure', { taskType: task.taskType })
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
