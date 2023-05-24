import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginTaskType, VMMethods } from '../../types'
import { processError } from '../../utils/db/error'
import { instrument } from '../../utils/metrics'
import { runRetriableFunction } from '../../utils/retries'
import { IllegalOperationError } from '../../utils/utils'
import { LazyPluginVM } from '../vm/lazy'
import { loadPlugin } from './loadPlugin'

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

    const pluginsSucceeded: string[] = event.properties?.$plugins_succeeded || []
    const pluginsFailed = event.properties?.$plugins_failed || []
    const pluginsDeferred = []
    const pluginsAlreadyProcessed = new Set([...pluginsSucceeded, ...pluginsFailed])
    for (const [pluginConfig, processEvent] of pluginMethodsToRun) {
        if (processEvent) {
            const timer = new Date()
            const pluginIdentifier = `${pluginConfig.plugin?.name} (${pluginConfig.id})`

            if (pluginsAlreadyProcessed.has(pluginIdentifier)) {
                continue
            }

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
                pluginsSucceeded.push(pluginIdentifier)
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
                pluginsFailed.push(pluginIdentifier)
                await hub.appMetrics.queueError(
                    {
                        teamId,
                        pluginConfigId: pluginConfig.id,
                        category: 'processEvent',
                        failures: 1,
                    },
                    {
                        error,
                        event,
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
    const pluginConfig = await getPluginConfig(hub, pluginConfigId)
    const teamId = pluginConfig?.team_id
    let shouldQueueAppMetric = false

    try {
        const task = await pluginConfig?.vm?.getTask(taskName, taskType)
        if (!task) {
            throw new Error(
                `Task "${taskName}" not found for plugin "${pluginConfig?.plugin?.name}" with config id ${pluginConfigId}`
            )
        }

        shouldQueueAppMetric = taskType === PluginTaskType.Schedule && !task.__ignoreForAppMetrics
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

        if (shouldQueueAppMetric && teamId) {
            await hub.appMetrics.queueMetric({
                teamId: teamId,
                pluginConfigId: pluginConfigId,
                category: 'scheduledTask',
                successes: 1,
            })
        }
    } catch (error) {
        await processError(hub, pluginConfig || null, error)

        hub.statsd?.increment(`plugin.task.ERROR`, {
            taskType: taskType,
            taskName: taskName,
            pluginConfigId: pluginConfigId.toString(),
            teamId: teamId?.toString() ?? '?',
        })

        if (shouldQueueAppMetric && teamId) {
            await hub.appMetrics.queueError(
                {
                    teamId: teamId,
                    pluginConfigId: pluginConfigId,
                    category: 'scheduledTask',
                    failures: 1,
                },
                { error }
            )
        }
    }
    hub.statsd?.timing(`plugin.task`, timer, {
        plugin: pluginConfig?.plugin?.name ?? '?',
        teamId: teamId?.toString() ?? '?',
    })
    return response
}

async function getPluginMethodsForTeam<M extends keyof VMMethods>(
    hub: Hub,
    teamId: number,
    method: M
): Promise<[PluginConfig, VMMethods[M]][]> {
    const pluginConfigs = await getPluginsForTeam(hub, teamId)
    if (pluginConfigs.length === 0) {
        return []
    }
    const methodsObtained = await Promise.all(
        pluginConfigs.map(async (pluginConfig) => [pluginConfig, await pluginConfig?.vm?.getVmMethod(method)])
    )
    return methodsObtained as [PluginConfig, VMMethods[M]][]
}

async function getPluginsForTeam(hub: Hub, teamId: number) {
    // Query all plugin configs for the given team. To avoid querying the
    // database for each event we cache, the plugin config promises are loaded
    // into the hub.pluginConfigs LRU. Note that we cache the promise rather
    // than the result, as we want to avoid a thundering herd of queries when
    // there are already running queries for the same team.
    const pluginConfigsCache = hub.pluginConfigsPerTeam.get(teamId)
    if (pluginConfigsCache) {
        return await pluginConfigsCache
    } else {
        const pluginConfigsPromise = initPluginsForTeam(hub, teamId)
        hub.pluginConfigsPerTeam.set(teamId, pluginConfigsPromise)
        return await pluginConfigsPromise
    }
}

async function initPluginsForTeam(hub: Hub, teamId: number) {
    // Query all plugin configs for the given team. To avoid querying the
    // database for each event we cache, the plugin config promises are loaded
    // into the hub.pluginConfigs LRU. Note that we cache the promise rather
    // than the result, as we want to avoid a thundering herd of queries when
    // there are already running queries for the same team.
    const pluginConfigs = await hub.db.postgresQuery<PluginConfig>(
        `SELECT * FROM posthog_pluginconfig WHERE team_id = $1 AND enabled = true`,
        [teamId],
        'getPluginConfigsForTeam'
    )

    // Load the plugin configs into the hub.
    return await Promise.all(pluginConfigs.rows.map((pluginConfig) => loadPluginConfig(hub, pluginConfig)))
}

async function loadPluginConfig(hub: Hub, pluginConfig: PluginConfig) {
    const pluginVM = new LazyPluginVM(hub, pluginConfig)
    await loadPlugin(hub, pluginConfig)
    pluginConfig.vm = pluginVM
    return pluginConfig
}

async function getPluginConfig(hub: Hub, pluginConfigId: number) {
    // Either get the pluginConfig with VM loaded from the cache, or load it
    // from the database.
    const pluginConfigCache = hub.pluginConfigs.get(pluginConfigId)
    if (pluginConfigCache) {
        return await pluginConfigCache
    }
    const pluginConfig = await initPluginConfig(hub, pluginConfigId)
    hub.pluginConfigs.set(pluginConfigId, Promise.resolve(pluginConfig))
    return pluginConfig
}

async function initPluginConfig(hub: Hub, pluginConfigId: number) {
    const pluginConfigRows = await hub.db.postgresQuery<PluginConfig>(
        `SELECT * FROM posthog_pluginconfig WHERE id = $1`,
        [pluginConfigId],
        'getPluginConfig'
    )
    if (pluginConfigRows.rowCount === 0) {
        throw new Error(`Plugin config ${pluginConfigId} not found`)
    }
    const pluginConfig = pluginConfigRows.rows[0]
    await loadPlugin(hub, pluginConfig)
    return pluginConfig
}
