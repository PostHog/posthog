import { Batch, EachBatchHandler, Kafka } from 'kafkajs'
import { KafkaProducerWrapper } from 'utils/db/kafka-producer-wrapper'

import { KAFKA_SCHEDULED_TASKS, KAFKA_SCHEDULED_TASKS_DLQ } from '../../config/kafka-topics'
import { PluginServerService, PluginsServerConfig } from '../../types'
import { DependencyUnavailableError } from '../../utils/db/error'
import { status } from '../../utils/status'
import Piscina from '../../worker/piscina'
import { instrumentEachBatchKafkaJS, setupEventHandlers } from './kafka-queue'
import { latestOffsetTimestampGauge, scheduledTaskCounter } from './metrics'
import { makeHealthCheck } from './on-event-handler-consumer'

// The valid task types that can be scheduled.
// TODO: not sure if there is another place that defines these but it would be good to unify.
const taskTypes = ['runEveryMinute', 'runEveryHour', 'runEveryDay'] as const

export const startScheduledTasksConsumer = async ({
    kafka,
    producer,
    piscina,
    serverConfig,
    partitionConcurrency = 3,
}: {
    kafka: Kafka
    producer: KafkaProducerWrapper
    piscina: Piscina
    serverConfig: PluginsServerConfig
    partitionConcurrency: number
}): Promise<PluginServerService> => {
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
    const consumer = kafka.consumer({
        groupId,
        sessionTimeout: serverConfig.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
        rebalanceTimeout: serverConfig.KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS ?? undefined,
    })
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

            // Make sure we keep the heartbeat going while the tasks is
            // running.
            const heartbeatInterval = setInterval(() => heartbeat(), 1000)

            try {
                // The part that actually runs the task.
                await piscina.run({ task: taskType, args: { pluginConfigId: pluginConfigId } })

                resolveOffset(message.offset)
                status.info('⏲️', 'finished_scheduled_task', {
                    taskType,
                    pluginConfigId,
                    durationSeconds: (performance.now() - startTime) / 1000,
                })
                scheduledTaskCounter.labels({ status: 'completed', task: taskType }).inc()
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
                    scheduledTaskCounter.labels({ status: 'error', task: taskType }).inc()
                    throw error
                }

                status.error('⚠️', 'scheduled_task_failed', {
                    taskType: taskType,
                    pluginConfigId,
                    error: error,
                    stack: error.stack,
                })
                resolveOffset(message.offset)
                scheduledTaskCounter.labels({ status: 'failed', task: taskType }).inc()
            } finally {
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
            return await instrumentEachBatchKafkaJS(KAFKA_SCHEDULED_TASKS, eachBatch, payload)
        },
    })

    const healthcheck = makeHealthCheck(consumer, serverConfig.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS)

    return {
        id: 'scheduled-tasks-consumer',
        healthcheck: async () => await healthcheck(),
        onShutdown: async () => await consumer.stop(),
    }
}

const getTasksFromBatch = async (batch: Batch, producer: KafkaProducerWrapper) => {
    // In any one batch, we only want to run one task per plugin config id.
    // Hence here we dedupe the tasks by plugin config id and task type.
    const tasksbyTypeAndPluginConfigId = {} as Record<
        (typeof taskTypes)[number],
        Record<
            number,
            { taskType: (typeof taskTypes)[number]; pluginConfigId: number; message: (typeof batch.messages)[number] }
        >
    >

    for (const message of batch.messages) {
        if (!message.value) {
            status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                value: message.value,
            })
            await producer.queueMessage({
                kafkaMessage: {
                    topic: KAFKA_SCHEDULED_TASKS_DLQ,
                    messages: [{ value: message.value, key: message.key }],
                },
                waitForAck: true,
            })
            continue
        }

        let task: {
            taskType: (typeof taskTypes)[number]
            pluginConfigId: number
        }

        try {
            task = JSON.parse(message.value.toString())
        } catch (error) {
            status.warn('⚠️', `Invalid message for partition ${batch.partition} offset ${message.offset}.`, {
                error: error.stack ?? error,
            })
            await producer.queueMessage({
                kafkaMessage: {
                    topic: KAFKA_SCHEDULED_TASKS_DLQ,
                    messages: [{ value: message.value, key: message.key }],
                },
                waitForAck: true,
            })
            continue
        }

        if (!taskTypes.includes(task.taskType) || isNaN(task.pluginConfigId)) {
            status.warn('⚠️', `Invalid schema for partition ${batch.partition} offset ${message.offset}.`, task)
            await producer.queueMessage({
                kafkaMessage: {
                    topic: KAFKA_SCHEDULED_TASKS_DLQ,
                    messages: [{ value: message.value, key: message.key }],
                },
                waitForAck: true,
            })
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
