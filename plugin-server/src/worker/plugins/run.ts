import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginTaskType, VMMethods } from '../../types'
import { processError } from '../../utils/db/error'
import { instrument } from '../../utils/metrics'
import { runRetriableFunction } from '../../utils/retries'
import { IllegalOperationError } from '../../utils/utils'

export async function runOnEvent(hub: Hub, event: ProcessedPluginEvent): Promise<void> {
    const pluginMethodsToRun = await getPluginMethodsForTeam(hub, event.team_id, 'onEvent')

    await Promise.all(
        pluginMethodsToRun
            .filter(([, method]) => !!method)
            .map(([pluginConfig, onEvent]) =>
                instrument(
                    hub.statsd,
                    {
                        metricName: 'plugin.runOnEvent',
                        key: 'plugin',
                        tag: pluginConfig.plugin?.name || '?',
                    },
                    () =>
                        runRetriableFunction({
                            hub,
                            metricName: 'plugin.on_event',
                            metricTags: {
                                plugin: pluginConfig.plugin?.name ?? '?',
                                teamId: event.team_id.toString(),
                            },
                            tryFn: async () => await onEvent!(event),
                            catchFn: async (error) => await processError(hub, pluginConfig, error, event),
                            payload: event,
                            appMetric: {
                                teamId: event.team_id,
                                pluginConfigId: pluginConfig.id,
                                category: 'onEvent',
                            },
                            appMetricErrorContext: { event },
                        })
                )
            )
    )
}

export async function runOnSnapshot(hub: Hub, event: ProcessedPluginEvent): Promise<void> {
    const pluginMethodsToRun = await getPluginMethodsForTeam(hub, event.team_id, 'onSnapshot')

    await Promise.all(
        pluginMethodsToRun
            .filter(([, method]) => !!method)
            .map(([pluginConfig, onSnapshot]) =>
                instrument(
                    hub.statsd,
                    {
                        metricName: 'plugin.runOnSnapshot',
                        key: 'plugin',
                        tag: pluginConfig.plugin?.name || '?',
                    },
                    () =>
                        runRetriableFunction({
                            hub,
                            metricName: 'plugin.on_snapshot',
                            metricTags: {
                                plugin: pluginConfig.plugin?.name ?? '?',
                                teamId: event.team_id.toString(),
                            },
                            tryFn: async () => await onSnapshot!(event),
                            catchFn: async (error) => await processError(hub, pluginConfig, error, event),
                            payload: event,
                        })
                )
            )
    )
}

export async function runProcessEvent(hub: Hub, event: PluginEvent): Promise<PluginEvent | null> {
    const teamId = event.team_id
    const pluginMethodsToRun = await getPluginMethodsForTeam(hub, teamId, 'processEvent')
    let returnedEvent: PluginEvent | null = event

    const pluginsSucceeded: string[] = []
    const pluginsFailed = []
    const pluginsDeferred = []
    for (const [pluginConfig, processEvent] of pluginMethodsToRun) {
        if (processEvent) {
            const timer = new Date()

            try {
                returnedEvent =
                    (await instrument(
                        hub.statsd,
                        {
                            metricName: 'plugin.processEvent',
                            key: 'plugin',
                            tag: pluginConfig.plugin?.name || '?',
                        },
                        () => processEvent(returnedEvent!)
                    )) || null
                if (returnedEvent && returnedEvent.team_id !== teamId) {
                    returnedEvent.team_id = teamId
                    throw new IllegalOperationError('Plugin tried to change event.team_id')
                }
                pluginsSucceeded.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
                await hub.appMetrics.queueMetric({
                    teamId,
                    pluginConfigId: pluginConfig.id,
                    category: 'processEvent',
                    successes: 1,
                })
            } catch (error) {
                await processError(hub, pluginConfig, error, returnedEvent)
                hub.statsd?.increment(`plugin.process_event.ERROR`, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: String(event.team_id),
                })
                pluginsFailed.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
                await hub.appMetrics.queueError(
                    {
                        teamId,
                        pluginConfigId: pluginConfig.id,
                        category: 'processEvent',
                        failures: 1,
                    },
                    {
                        error: error,
                        context: { event },
                    }
                )
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
        response = await instrument(
            hub.statsd,
            {
                metricName: 'plugin.runTask',
                key: 'plugin',
                tag: pluginConfig?.plugin?.name || '?',
                data: {
                    taskName,
                    taskType,
                },
            },
            () => (payload ? task?.exec(payload) : task?.exec())
        )
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
