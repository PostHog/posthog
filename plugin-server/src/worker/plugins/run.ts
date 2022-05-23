import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { Alert, Hub, PluginConfig, PluginTaskType, TeamId } from '../../types'
import { processError } from '../../utils/db/error'
import { IllegalOperationError } from '../../utils/utils'
import { Action } from './../../types'

export async function runOnEvent(server: Hub, event: ProcessedPluginEvent): Promise<void> {
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
                    server.statsd?.increment(`plugin.on_event.ERROR`, {
                        plugin: pluginConfig.plugin?.name ?? '?',
                        teamId: event.team_id.toString(),
                    })
                }
                server.statsd?.timing(`plugin.on_event`, timer, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: event.team_id.toString(),
                })
            }
        })
    )
}

export async function runOnAction(server: Hub, action: Action, event: ProcessedPluginEvent): Promise<void> {
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
                    server.statsd?.increment(`plugin.on_action.ERROR`, {
                        plugin: pluginConfig.plugin?.name ?? '?',
                        teamId: event.team_id.toString(),
                    })
                }
                server.statsd?.timing(`plugin.on_action`, timer, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: event.team_id.toString(),
                })
            }
        })
    )
}

export async function runOnSnapshot(server: Hub, event: ProcessedPluginEvent): Promise<void> {
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
                    server.statsd?.increment(`plugin.on_snapshot.ERROR`, {
                        plugin: pluginConfig.plugin?.name ?? '?',
                        teamId: event.team_id.toString(),
                    })
                }
                server.statsd?.timing(`plugin.on_snapshot`, timer, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: event.team_id.toString(),
                })
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
                server.statsd?.increment(`plugin.process_event.ERROR`, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: String(event.team_id),
                })
                pluginsFailed.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
            }
            server.statsd?.timing(`plugin.process_event`, timer, {
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
        let teamIdStr = '?'
        if (pluginConfig != null) {
            teamIdStr = pluginConfig.team_id.toString()
        }

        server.statsd?.increment(`plugin.task.ERROR`, {
            taskType: taskType,
            taskName: taskName,
            pluginConfigId: pluginConfigId.toString(),
            teamId: teamIdStr,
        })
    }
    return response
}

function getPluginsForTeam(server: Hub, teamId: number): PluginConfig[] {
    return server.pluginConfigsPerTeam.get(teamId) || []
}

function getPluginsForTeams(server: Hub, teamIds: TeamId[]) {
    let plugins: PluginConfig[] = []
    for (const teamId of teamIds) {
        plugins = plugins.concat(getPluginsForTeam(server, teamId))
    }
    return plugins
}
