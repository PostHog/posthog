import Piscina from '@posthog/piscina'
import { StatsD } from 'hot-shots'
import { EachBatchHandler, Kafka, Producer } from 'kafkajs'

import { KAFKA_SCHEDULED_TASKS, KAFKA_SCHEDULED_TASKS_DLQ } from '../../config/kafka-topics'
import { DependencyUnavailableError } from '../../utils/db/error'
import { status } from '../../utils/status'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'

// The valid task types that can be scheduled.
// TODO: not sure if there is another place that defines these but it would be
// good to unify.
const taskTypes = ['runEveryMinute', 'runEveryHour', 'runEveryDay'] as const

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
        Piscina worker. Some features include:

         1. timing out tasks to ensure we don't end up with backlogs.
         2. retrying on dependency failures (via not committing offsets on seom
            failues).
         3. only running one plugin config id task at a time (to avoid
            concurrency issues). This is done via partitioning of tasks in the
            Kafka topic.

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
                await producer.send({ topic: KAFKA_SCHEDULED_TASKS_DLQ, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            let task: {
                taskType: typeof taskTypes[number]
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

            if (!taskTypes.includes(task.taskType) || isNaN(task.pluginConfigId)) {
                status.warn('⚠️', `Invalid schema for partition ${batch.partition} offset ${message.offset}.`, task)
                await producer.send({ topic: KAFKA_SCHEDULED_TASKS_DLQ, messages: [message] })
                resolveOffset(message.offset)
                continue
            }

            status.debug('⬆️', 'Running scheduled task', task)

            try {
                status.info('⏲️', 'running_scheduled_task', {
                    taskType: task.taskType,
                    pluginConfigId: task.pluginConfigId,
                })
                const startTime = performance.now()

                // Make sure tasks can't run forever, according to `taskTimeouts`.
                const abortController = new AbortController()
                const timeout = setTimeout(() => {
                    abortController.abort()
                    status.warn('⚠️', 'scheduled_task_timed_out', {
                        taskType: task.taskType,
                        pluginConfigId: task.pluginConfigId,
                    })
                }, taskTimeouts[task.taskType])

                // The part that actually runs the task.
                await piscina.run(
                    { task: task.taskType, args: { pluginConfigId: task.pluginConfigId } },
                    { signal: abortController.signal }
                )

                clearTimeout(timeout)

                resolveOffset(message.offset)
                status.info('⏲️', 'finished_scheduled_task', {
                    taskType: task.taskType,
                    pluginConfigId: task.pluginConfigId,
                    durationSeconds: (performance.now() - startTime) / 1000,
                })
                statsd?.increment('completed_scheduled_task', { taskType: task.taskType })
            } catch (error) {
                if (error instanceof DependencyUnavailableError) {
                    // For errors relating to PostHog dependencies that are unavailable,
                    // e.g. Postgres, Kafka, Redis, we don't want to log the error to Sentry
                    // but rather bubble this up the stack for someone else to decide on
                    // what to do with it.
                    status.warn('⚠️', `dependency_unavailable`, {
                        taskType: task.taskType,
                        pluginConfigId: task.pluginConfigId,
                        error: error,
                        stack: error.stack,
                    })
                    statsd?.increment('retriable_scheduled_task', { taskType: task.taskType })
                    throw error
                }

                status.error('⚠️', 'scheduled_task_failed', {
                    taskType: task.taskType,
                    pluginConfigId: task.pluginConfigId,
                    error: error,
                    stack: error.stack,
                })
                statsd?.increment('failed_scheduled_tasks', { taskType: task.taskType })
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

const taskTimeouts = {
    runEveryMinute: 1000 * 60,
    runEveryHour: 1000 * 60 * 5,
    runEveryDay: 1000 * 60 * 5,
} as const
