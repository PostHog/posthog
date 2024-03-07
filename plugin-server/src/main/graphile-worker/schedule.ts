import { JobHelpers } from 'graphile-worker'

import { KAFKA_SCHEDULED_TASKS } from '../../config/kafka-topics'
import { Hub, PluginConfigId } from '../../types'
import { DependencyUnavailableError } from '../../utils/db/error'
import { status } from '../../utils/status'
import { delay } from '../../utils/utils'
import Piscina from '../../worker/piscina'
import { scheduledTaskCounter } from '../ingestion-queues/metrics'
import { graphileScheduledTaskCounter } from './metrics'

type TaskTypes = 'runEveryMinute' | 'runEveryHour' | 'runEveryDay'

export async function loadPluginSchedule(piscina: Piscina, maxIterations = 2000): Promise<Hub['pluginSchedule']> {
    let allThreadsReady = false
    while (maxIterations--) {
        // Make sure the schedule loaded successfully on all threads
        if (!allThreadsReady) {
            const threadsScheduleReady = await piscina.broadcastTask({ task: 'pluginScheduleReady' })
            allThreadsReady = threadsScheduleReady.every((res: any) => res)
        }

        if (allThreadsReady) {
            // Having ensured the schedule is loaded on all threads, pull it from only one of them
            const schedule = (await piscina.run({ task: 'getPluginSchedule' })) as Record<
                string,
                PluginConfigId[]
            > | null
            if (schedule) {
                return schedule
            }
        }
        await delay(200)
    }
    throw new Error('Could not load plugin schedule in time')
}

export async function runScheduledTasks(
    server: Hub,
    piscina: Piscina,
    taskType: TaskTypes,
    helpers: JobHelpers
): Promise<void> {
    // If the tasks run_at is older than the grace period, we ignore it. We
    // don't want to end up with old tasks being scheduled if we are backed up.
    if (new Date(helpers.job.run_at).getTime() < Date.now() - gracePeriodMilliSecondsByTaskType[taskType]) {
        status.warn('🔁', 'stale_scheduled_task_skipped', {
            taskType: taskType,
            runAt: helpers.job.run_at,
        })
        graphileScheduledTaskCounter.labels({ status: 'skipped', task: taskType }).inc()
        return
    }

    if (server.USE_KAFKA_FOR_SCHEDULED_TASKS) {
        for (const pluginConfigId of server.pluginSchedule?.[taskType] || []) {
            status.info('⏲️', 'queueing_schedule_task', { taskType, pluginConfigId })
            await server.kafkaProducer.queueMessage({
                topic: KAFKA_SCHEDULED_TASKS,
                messages: [{ key: pluginConfigId.toString(), value: JSON.stringify({ taskType, pluginConfigId }) }],
            })
            graphileScheduledTaskCounter.labels({ status: 'queued', task: taskType }).inc()
        }
    } else {
        for (const pluginConfigId of server.pluginSchedule?.[taskType] || []) {
            try {
                status.info('⏲️', 'running_scheduled_task', {
                    taskType,
                    pluginConfigId,
                })
                const startTime = performance.now()

                // The part that actually runs the task.
                await piscina.run({ task: taskType, args: { pluginConfigId } })

                status.info('⏲️', 'finished_scheduled_task', {
                    taskType,
                    pluginConfigId,
                    durationSeconds: (performance.now() - startTime) / 1000,
                })
                scheduledTaskCounter.labels({ status: 'completed', task: taskType }).inc()
            } catch (error) {
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
                scheduledTaskCounter.labels({ status: 'failed', task: taskType }).inc()
            }
            graphileScheduledTaskCounter.labels({ status: 'completed', task: taskType }).inc()
        }
    }
}

const gracePeriodMilliSecondsByTaskType = {
    runEveryMinute: 60 * 1000,
    runEveryHour: 60 * 60 * 1000,
    runEveryDay: 24 * 60 * 60 * 1000,
} as const
