import Piscina from '@posthog/piscina'
import { StatsD } from 'hot-shots'
import { Batch, EachBatchHandler, Kafka, Producer } from 'kafkajs'

import { KAFKA_SCHEDULED_TASKS, KAFKA_SCHEDULED_TASKS_DLQ } from '../../config/kafka-topics'
import { DependencyUnavailableError } from '../../utils/db/error'
import { status } from '../../utils/status'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'
import { latestOffsetTimestampGauge } from './metrics'

// The valid task types that can be scheduled.
// TODO: not sure if there is another place that defines these but it would be
// good to unify.
const taskTypes = ['runEveryMinute', 'runEveryHour', 'runEveryDay'] as const

export const startScheduledTasksConsumer = async ({
    kafka,
    piscina,
    producer,
    partitionConcurrency = 3,
    statsd,
}: {
    kafka: Kafka
    piscina: Piscina
    producer: Producer // NOTE: not using KafkaProducerWrapper here to avoid buffering logic
    partitionConcurrency: number
    statsd?: StatsD
}) => {
    /*

        Consumes from the scheduled tasks topic, and executes them within a
        Piscina worker. Some features include:

         1. timing out tasks to ensure we don't end up with backlogs.
         2. retrying on dependency failures (via not committing offsets on seom
            failues).
         3. only running one plugin config id task at a time, to avoid
            concurrency issues. This is done via partitioning of tasks in the
            Kafka topic.
         4. ensuring we only run one task per plugin config id per batch, to
            avoid running many tasks back to back in the case that we have a
            backlog of tasks in the topic.

        TODO: add in some in partition concurrency control.

    */

    const groupId = 'scheduled-tasks-runner'
    const consumer = kafka.consumer({ groupId })
    setupEventHandlers(consumer)

    status.info('🔁', 'Starting scheduled tasks consumer')

    const eachBatch: EachBatchHandler = async ({ batch, resolveOffset, heartbeat, commitOffsetsIfNecessary }) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })

        const tasks = await getTasksFromBatch(batch, producer)

        for (const { taskType, pluginConfigId, message } of tasks) {
            status.info('⏲️', 'running_scheduled_task', {
                taskType,
                pluginConfigId,
            })
            const startTime = performance.now()

            // Make sure tasks can't run forever, according to `taskTimeouts`.
            const abortController = new AbortController()
            const timeout = setTimeout(() => {
                abortController.abort()
                status.warn('⚠️', 'scheduled_task_timed_out', {
                    taskType,
                    pluginConfigId,
                })
            }, taskTimeouts[taskType])

            // Make sure we keep the heartbeat going while the tasks is
            // running.
            const heartbeatInterval = setInterval(() => heartbeat(), 1000)

            try {
                // The part that actually runs the task.
                await piscina.run(
                    { task: taskType, args: { pluginConfigId: pluginConfigId } },
                    { signal: abortController.signal }
                )

                resolveOffset(message.offset)
                status.info('⏲️', 'finished_scheduled_task', {
                    taskType,
                    pluginConfigId,
                    durationSeconds: (performance.now() - startTime) / 1000,
                })
                statsd?.increment('completed_scheduled_task', { taskType })
            } catch (error) {
                // TODO: figure out a nice way to test this code path.

                if (error instanceof DependencyUnavailableError) {
                    // For errors relating to PostHog dependencies that are unavailable,
                    // e.g. Postgres, Kafka, Redis, we don't want to log the error to Sentry
                    // but rather bubble this up the stack for someone else to decide on
                    // what to do with it.
                    status.warn('⚠️', `dependency_unavailable`, {
                        taskType,
                        pluginConfigId,
                        error: error,
                        stack: error.stack,
                    })
                    statsd?.increment('retriable_scheduled_task', { taskType })
                    throw error
                }

                status.error('⚠️', 'scheduled_task_failed', {
                    taskType: taskType,
                    pluginConfigId,
                    error: error,
                    stack: error.stack,
                })
                resolveOffset(message.offset)
                statsd?.increment('failed_scheduled_tasks', { taskType })
            } finally {
                clearTimeout(timeout)
                clearInterval(heartbeatInterval)
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

        status.debug('✅', 'processed_batch', { batchSize: batch.messages.length, numberOfTasksExecuted: tasks.length })
    }

    await consumer.connect()
    await consumer.subscribe({ topic: KAFKA_SCHEDULED_TASKS })
    await consumer.run({
        partitionsConsumedConcurrently: partitionConcurrency,
        eachBatch: async (payload) => {
            return await instrumentEachBatch(KAFKA_SCHEDULED_TASKS, eachBatch, payload, statsd)
        },
    })

    return consumer
}

const getTasksFromBatch = async (batch: Batch, producer: Producer) => {
    // In any one batch, we only want to run one task per plugin config id.
    // Hence here we dedupe the tasks by plugin config id and task type.
    const tasksbyTypeAndPluginConfigId = {} as Record<
        typeof taskTypes[number],
        Record<
            number,
            { taskType: typeof taskTypes[number]; pluginConfigId: number; message: typeof batch.messages[number] }
        >
    >

    for (const message of batch.messages) {
        if (!message.value) {
            status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                value: message.value,
            })
            await producer.send({ topic: KAFKA_SCHEDULED_TASKS_DLQ, messages: [message] })
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
            continue
        }

        if (!taskTypes.includes(task.taskType) || isNaN(task.pluginConfigId)) {
            status.warn('⚠️', `Invalid schema for partition ${batch.partition} offset ${message.offset}.`, task)
            await producer.send({ topic: KAFKA_SCHEDULED_TASKS_DLQ, messages: [message] })
            continue
        }

        tasksbyTypeAndPluginConfigId[task.taskType] ??= {}
        // It's important that we only keep the latest message for each,
        // such that we commit the offset at the end of the batch.
        tasksbyTypeAndPluginConfigId[task.taskType][task.pluginConfigId] = {
            taskType: task.taskType,
            pluginConfigId: task.pluginConfigId,
            message,
        }
    }

    return Object.values(tasksbyTypeAndPluginConfigId)
        .map((tasksByPluginConfigId) => Object.values(tasksByPluginConfigId))
        .flat()
        .sort((a, b) => Number.parseInt(a.message.offset) - Number.parseInt(b.message.offset))
}

const taskTimeouts = {
    runEveryMinute: 1000 * 60,
    runEveryHour: 1000 * 60 * 5,
    runEveryDay: 1000 * 60 * 5,
} as const
