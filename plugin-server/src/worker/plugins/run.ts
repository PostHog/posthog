import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginTaskType, VMMethods } from '../../types'
import { processError } from '../../utils/db/error'
import { IllegalOperationError } from '../../utils/utils'
import { runRetriableFunction } from '../retries'

export async function runOnEvent(hub: Hub, event: ProcessedPluginEvent): Promise<void> {
    const pluginMethodsToRun = await getPluginMethodsForTeam(hub, event.team_id, 'onEvent')

    await Promise.all(
        pluginMethodsToRun
            .filter(([, method]) => !!method)
            .map(
                async ([pluginConfig, onEvent]) =>
                    await runRetriableFunction('on_event', hub, pluginConfig, {
                        tryFn: async () => await onEvent!(event),
                        event,
                    })
            )
    )
}

export async function runOnSnapshot(hub: Hub, event: ProcessedPluginEvent): Promise<void> {
    const pluginMethodsToRun = await getPluginMethodsForTeam(hub, event.team_id, 'onSnapshot')

    await Promise.all(
        pluginMethodsToRun
            .filter(([, method]) => !!method)
            .map(
                async ([pluginConfig, onSnapshot]) =>
                    await runRetriableFunction('on_snapshot', hub, pluginConfig, {
                        tryFn: async () => await onSnapshot!(event),
                        event,
                    })
            )
    )
}

export async function runProcessEvent(hub: Hub, event: PluginEvent): Promise<PluginEvent | null> {
    const teamId = event.team_id
    const pluginMethodsToRun = await getPluginMethodsForTeam(hub, teamId, 'processEvent')
    let returnedEvent: PluginEvent | null = event

    const pluginsSucceeded = []
    const pluginsFailed = []
    const pluginsDeferred = []
    for (const [pluginConfig, processEvent] of pluginMethodsToRun) {
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

async function getPluginMethodsForTeam<M extends keyof VMMethods>(
    hub: Hub,
    teamId: number,
    method: M
): Promise<[PluginConfig, VMMethods[M]][]> {
    const pluginConfigs = hub.pluginConfigsPerTeam.get(teamId) || []
    if (pluginConfigs.length === 0) {
        return []
    }
    const methodsObtained = await Promise.all(
        pluginConfigs.map(async (pluginConfig) => [pluginConfig, await pluginConfig?.vm?.getVmMethod(method)])
    )
    return methodsObtained as [PluginConfig, VMMethods[M]][]
}
