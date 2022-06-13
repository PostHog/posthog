import { PluginEvent, ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginTaskType } from '../../types'
import { processError } from '../../utils/db/error'
import { delay, IllegalOperationError } from '../../utils/utils'
import { Action } from './../../types'

export const ON_CAUSE_MAX_ATTEMPTS = 5
export const ON_CAUSE_RETRY_MULTIPLIER = 2
export const ON_CAUSE_RETRY_BASE_MS = 5000

export async function runOnEvent(hub: Hub, event: ProcessedPluginEvent): Promise<void> {
    const pluginsToRun = getPluginsForTeam(hub, event.team_id)

    await Promise.all(
        pluginsToRun.map(async (pluginConfig) => {
            const onEvent = await pluginConfig.vm?.getOnEvent()
            if (onEvent) {
                await runRetriableFunction(hub, pluginConfig, event, 'on_event', async () => await onEvent(event))
            }
        })
    )
}

export async function runOnSnapshot(hub: Hub, event: ProcessedPluginEvent): Promise<void> {
    const pluginsToRun = getPluginsForTeam(hub, event.team_id)

    await Promise.all(
        pluginsToRun.map(async (pluginConfig) => {
            const onSnapshot = await pluginConfig.vm?.getOnSnapshot()
            if (onSnapshot) {
                await runRetriableFunction(hub, pluginConfig, event, 'on_snapshot', async () => await onSnapshot(event))
            }
        })
    )
}

export async function runOnAction(hub: Hub, action: Action, event: ProcessedPluginEvent): Promise<void> {
    const pluginsToRun = getPluginsForTeam(hub, event.team_id)

    await Promise.all(
        pluginsToRun.map(async (pluginConfig) => {
            const onAction = await pluginConfig.vm?.getOnAction()
            if (onAction) {
                await runRetriableFunction(
                    hub,
                    pluginConfig,
                    event,
                    'on_action',
                    async () => await onAction(action, event)
                )
            }
        })
    )
}

export async function runProcessEvent(hub: Hub, event: PluginEvent): Promise<PluginEvent | null> {
    const pluginsToRun = getPluginsForTeam(hub, event.team_id)
    const teamId = event.team_id
    let returnedEvent: PluginEvent | null = event

    const pluginsSucceeded = []
    const pluginsFailed = []
    const pluginsDeferred = []
    for (const pluginConfig of pluginsToRun) {
        const processEvent = await pluginConfig.vm?.getProcessEvent()

        if (processEvent) {
            const timer = new Date()

            try {
                returnedEvent = (await processEvent(returnedEvent)) || null
                if (returnedEvent && returnedEvent.team_id !== teamId) {
                    returnedEvent.team_id = teamId
                    throw new IllegalOperationError('Plugin tried to change event.team_id')
                }
                pluginsSucceeded.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
            } catch (error) {
                await processError(hub, pluginConfig, error, returnedEvent)
                hub.statsd?.increment(`plugin.process_event.ERROR`, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: String(event.team_id),
                })
                pluginsFailed.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
            }
            hub.statsd?.timing(`plugin.process_event`, timer, {
                plugin: pluginConfig.plugin?.name ?? '?',
                teamId: teamId.toString(),
            })

            if (!returnedEvent) {
                return null
            }
        }

        const onEvent = await pluginConfig.vm?.getOnEvent()
        const onSnapshot = await pluginConfig.vm?.getOnSnapshot()
        if (onEvent || onSnapshot) {
            pluginsDeferred.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
        }
    }

    if (pluginsSucceeded.length > 0 || pluginsFailed.length > 0 || pluginsDeferred.length > 0) {
        event.properties = {
            ...event.properties,
            $plugins_succeeded: pluginsSucceeded,
            $plugins_failed: pluginsFailed,
            $plugins_deferred: pluginsDeferred,
        }
    }

    return returnedEvent
}

export async function runPluginTask(
    hub: Hub,
    taskName: string,
    taskType: PluginTaskType,
    pluginConfigId: number,
    payload?: Record<string, any>
): Promise<any> {
    const timer = new Date()
    let response
    const pluginConfig = hub.pluginConfigs.get(pluginConfigId)
    const teamIdStr = pluginConfig?.team_id.toString() || '?'
    try {
        const task = await pluginConfig?.vm?.getTask(taskName, taskType)
        if (!task) {
            throw new Error(
                `Task "${taskName}" not found for plugin "${pluginConfig?.plugin?.name}" with config id ${pluginConfig}`
            )
        }
        response = await (payload ? task?.exec(payload) : task?.exec())
    } catch (error) {
        await processError(hub, pluginConfig || null, error)

        hub.statsd?.increment(`plugin.task.ERROR`, {
            taskType: taskType,
            taskName: taskName,
            pluginConfigId: pluginConfigId.toString(),
            teamId: teamIdStr,
        })
    }
    hub.statsd?.timing(`plugin.task`, timer, {
        plugin: pluginConfig?.plugin?.name ?? '?',
        teamId: teamIdStr,
    })
    return response
}

/** Run function with `RetryError` handling. */
async function runRetriableFunction(
    hub: Hub,
    pluginConfig: PluginConfig,
    event: ProcessedPluginEvent,
    tag: string,
    tryFunc: () => Promise<void>,
    catchFunc?: (error: Error) => Promise<void>,
    finallyFunc?: () => Promise<void>
): Promise<void> {
    const timer = new Date()
    let attempt = 0
    const teamIdString = event.team_id.toString()
    while (true) {
        attempt++
        let nextRetryMs: number
        try {
            await tryFunc()
            break
        } catch (error) {
            if (error instanceof RetryError) {
                error._attempt = attempt
                error._maxAttempts = ON_CAUSE_MAX_ATTEMPTS
            }
            if (error instanceof RetryError && attempt < ON_CAUSE_MAX_ATTEMPTS) {
                nextRetryMs = ON_CAUSE_RETRY_BASE_MS * ON_CAUSE_RETRY_MULTIPLIER ** attempt
                hub.statsd?.increment(`plugin.${tag}.RETRY`, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: teamIdString,
                    attempt: attempt.toString(),
                })
            } else {
                await catchFunc?.(error)
                await processError(hub, pluginConfig, error, event)
                hub.statsd?.increment(`plugin.${tag}.ERROR`, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: teamIdString,
                    attempt: attempt.toString(),
                })
                break
            }
        }
        await delay(nextRetryMs)
    }
    await finallyFunc?.()
    hub.statsd?.timing(`plugin.${tag}`, timer, {
        plugin: pluginConfig.plugin?.name ?? '?',
        teamId: teamIdString,
    })
}

function getPluginsForTeam(server: Hub, teamId: number): PluginConfig[] {
    return server.pluginConfigsPerTeam.get(teamId) || []
}
