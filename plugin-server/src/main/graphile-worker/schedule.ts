import { JobHelpers } from 'graphile-worker'

import { KAFKA_SCHEDULED_TASKS } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import Piscina from '../../worker/piscina'

type TaskTypes = 'runEveryMinute' | 'runEveryHour' | 'runEveryDay'

export async function loadPluginSchedule(hub: Hub): Promise<Hub['pluginSchedule']> {
    // Queries Postgres to retrieve a mapping from task type (runEveryMinute,
    // runEveryHour, runEveryDay) to a list of plugin config ids that are
    // registered as providing the task. We use the capabilities JSONB column to
    // filter on plugins that contain a `scheduled_task` key.
    status.info('📅', 'loading_plugin_schedule')
    const schedules = await hub.db.postgresQuery<{
        id: number
        task_types: 'runEveryMinute' | 'runEveryHour' | 'runEveryDay'[]
    }>(
        `
            SELECT 
                config.id AS id, 
                plugin.capabilities->'scheduled_tasks' AS task_types
            FROM posthog_pluginconfig config
            JOIN posthog_plugin plugin
                ON plugin.id = config.plugin_id
            JOIN posthog_team team
                ON team.id = config.team_id
            JOIN posthog_organization org
                ON org.id = team.organization_id
            WHERE 
                plugin.capabilities ? 'scheduled_tasks'
                AND config.enabled = true
                AND org.plugins_access_level > 0
        `,
        undefined,
        'loadPluginSchedule'
    )

    // Reduce the rows into a mapping from task type to plugin config ids.
    const schedule = schedules.rows.reduce((acc, { id, task_types }) => {
        for (const taskType of task_types) {
            acc[taskType] = acc[taskType] || []
            acc[taskType].push(id)
        }
        return acc
    }, {} as { [taskType: string]: number[] })

    status.info('📅', 'loaded_plugin_schedule', { schedule })
    return schedule
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
        server.statsd?.increment('skipped_scheduled_tasks', { taskType })
        return
    }

    if (server.USE_KAFKA_FOR_SCHEDULED_TASKS) {
        for (const pluginConfigId of server.pluginSchedule?.[taskType] || []) {
            status.info('⏲️', 'queueing_schedule_task', { taskType, pluginConfigId })
            await server.kafkaProducer.queueMessage({
                topic: KAFKA_SCHEDULED_TASKS,
                messages: [{ key: pluginConfigId.toString(), value: JSON.stringify({ taskType, pluginConfigId }) }],
            })
            server.statsd?.increment('queued_scheduled_task', { taskType })
        }
    } else {
        for (const pluginConfigId of server.pluginSchedule?.[taskType] || []) {
            status.info('⏲️', `Running ${taskType} for plugin config with ID ${pluginConfigId}`)
            await piscina.run({ task: taskType, args: { pluginConfigId } })
            server.statsd?.increment('completed_scheduled_task', { taskType })
        }
    }
}

const gracePeriodMilliSecondsByTaskType = {
    runEveryMinute: 60 * 1000,
    runEveryHour: 60 * 60 * 1000,
    runEveryDay: 24 * 60 * 60 * 1000,
} as const
