import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginFunction, PluginTaskType, TeamId } from '../../types'
import { processError } from '../../utils/db/error'
import { statusReport } from '../../utils/status-report'
import { IllegalOperationError } from '../../utils/utils'
import { Action } from './../../types'

function captureTimeSpentRunning(teamId: TeamId, timer: Date, func: PluginFunction): void {
    const timeSpentRunning = new Date().getTime() - timer.getTime()
    statusReport.addToTimeSpentRunningPlugins(teamId, timeSpentRunning, func)
}

export async function runOnEvent(server: Hub, event: PluginEvent): Promise<void> {
    const pluginsToRun = getPluginsForTeam(server, event.team_id)

    await Promise.all(
        pluginsToRun.map(async (pluginConfig) => {
            const onEvent = await pluginConfig.vm?.getOnEvent()
            if (onEvent) {
                const timer = new Date()
                try {
                    await onEvent(event)
                } catch (error) {
                    await processError(server, pluginConfig, error, event)
                    server.statsd?.increment(`plugin.${pluginConfig.plugin?.name}.on_event.ERROR`)
                }
                server.statsd?.timing(`plugin.${pluginConfig.plugin?.name}.on_event`, timer)
                captureTimeSpentRunning(event.team_id, timer, 'onEvent')
            }
        })
    )
}

export async function runOnAction(server: Hub, action: Action, event: PluginEvent): Promise<void> {
    const pluginsToRun = getPluginsForTeam(server, event.team_id)

    await Promise.all(
        pluginsToRun.map(async (pluginConfig) => {
            const onAction = await pluginConfig.vm?.getOnAction()
            if (onAction) {
                const timer = new Date()
                try {
                    await onAction(action, event)
                } catch (error) {
                    await processError(server, pluginConfig, error, event)
                    server.statsd?.increment(`plugin.${pluginConfig.plugin?.name}.on_action.ERROR`)
                }
                server.statsd?.timing(`plugin.${pluginConfig.plugin?.name}.on_action`, timer)
                captureTimeSpentRunning(event.team_id, timer, 'onAction')
            }
        })
    )
}

export async function runOnSnapshot(server: Hub, event: PluginEvent): Promise<void> {
    const pluginsToRun = getPluginsForTeam(server, event.team_id)

    await Promise.all(
        pluginsToRun.map(async (pluginConfig) => {
            const onSnapshot = await pluginConfig.vm?.getOnSnapshot()
            if (onSnapshot) {
                const timer = new Date()
                try {
                    await onSnapshot(event)
                } catch (error) {
                    await processError(server, pluginConfig, error, event)
                    server.statsd?.increment(`plugin.${pluginConfig.plugin?.name}.on_snapshot.ERROR`)
                }
                server.statsd?.timing(`plugin.${pluginConfig.plugin?.name}.on_snapshot`, timer)
                captureTimeSpentRunning(event.team_id, timer, 'onSnapshot')
            }
        })
    )
}

export async function runProcessEvent(server: Hub, event: PluginEvent): Promise<PluginEvent | null> {
    const teamId = event.team_id
    const pluginsToRun = getPluginsForTeam(server, teamId)
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
                await processError(server, pluginConfig, error, returnedEvent)
                server.statsd?.increment(`plugin.${pluginConfig.plugin?.name}.process_event.ERROR`)
                pluginsFailed.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
            }
            server.statsd?.timing(`plugin.process_event`, timer, {
                plugin: pluginConfig.plugin?.name ?? '?',
                teamId: teamId.toString(),
            })
            captureTimeSpentRunning(event.team_id, timer, 'processEvent')

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
    server: Hub,
    taskName: string,
    taskType: PluginTaskType,
    pluginConfigId: number,
    payload?: Record<string, any>
): Promise<any> {
    const timer = new Date()
    let response
    const pluginConfig = server.pluginConfigs.get(pluginConfigId)
    try {
        const task = await pluginConfig?.vm?.getTask(taskName, taskType)
        if (!task) {
            throw new Error(
                `Task "${taskName}" not found for plugin "${pluginConfig?.plugin?.name}" with config id ${pluginConfig}`
            )
        }
        response = await (payload ? task?.exec(payload) : task?.exec())
    } catch (error) {
        await processError(server, pluginConfig || null, error)
        server.statsd?.increment(`plugin.task.${taskType}.${taskName}.${pluginConfigId}.ERROR`)
    }
    captureTimeSpentRunning(pluginConfig?.team_id || 0, timer, 'pluginTask')
    return response
}

function getPluginsForTeam(server: Hub, teamId: number): PluginConfig[] {
    return server.pluginConfigsPerTeam.get(teamId) || []
}
