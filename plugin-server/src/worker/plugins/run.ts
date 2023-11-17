import { PluginEvent, PostHogEvent, ProcessedPluginEvent, Webhook } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginTaskType, VMMethods } from '../../types'
import { processError } from '../../utils/db/error'
import { trackedFetch } from '../../utils/fetch'
import { instrument } from '../../utils/metrics'
import { status } from '../../utils/status'
import { IllegalOperationError } from '../../utils/utils'

async function runSingleTeamPluginOnEvent(
    hub: Hub,
    event: ProcessedPluginEvent,
    pluginConfig: PluginConfig,
    onEvent: any
): Promise<void> {
    const timeout = setTimeout(() => {
        status.warn('⌛', `Still running single onEvent plugin for team ${event.team_id} for plugin ${pluginConfig.id}`)
    }, 10 * 1000) // 10 seconds
    try {
        // Runs onEvent for a single plugin without any retries
        const metricName = 'plugin.on_event'
        const metricTags = {
            plugin: pluginConfig.plugin?.name ?? '?',
            teamId: event.team_id.toString(),
        }

        const timer = new Date()
        try {
            await onEvent!(event)
            await hub.appMetrics.queueMetric({
                teamId: event.team_id,
                pluginConfigId: pluginConfig.id,
                category: 'onEvent',
                successes: 1,
            })
        } catch (error) {
            hub.statsd?.increment(`${metricName}.ERROR`, metricTags)
            await processError(hub, pluginConfig, error, event)
            await hub.appMetrics.queueError(
                {
                    teamId: event.team_id,
                    pluginConfigId: pluginConfig.id,
                    category: 'onEvent',
                    failures: 1,
                },
                {
                    error,
                    event,
                }
            )
        }
        hub.statsd?.timing(metricName, timer, metricTags)
    } finally {
        clearTimeout(timeout)
    }
}

export async function runOnEvent(hub: Hub, event: ProcessedPluginEvent): Promise<void> {
    // Runs onEvent for all plugins for this team in parallel
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
                    () => runSingleTeamPluginOnEvent(hub, event, pluginConfig, onEvent)
                )
            )
    )
}

async function runSingleTeamPluginComposeWebhook(
    hub: Hub,
    event: PostHogEvent,
    pluginConfig: PluginConfig,
    composeWebhook: any
): Promise<void> {
    const slowWarningTimeout = hub.EXTERNAL_REQUEST_TIMEOUT_MS * 0.7
    const timeout = setTimeout(() => {
        status.warn(
            '⌛',
            `Still running single composeWebhook plugin for team ${event.team_id} for plugin ${pluginConfig.id}`
        )
    }, slowWarningTimeout)
    try {
        // Runs composeWebhook for a single plugin without any retries
        const metricName = 'plugin.compose_webhook'
        const metricTags = {
            plugin: pluginConfig.plugin?.name ?? '?',
            teamId: event.team_id.toString(),
        }
        const timer = new Date()
        try {
            const webhook: Webhook | null = await composeWebhook!(event)
            if (!webhook) {
                // TODO: ideally we'd queryMetric it as skipped, but that's not an option atm
                status.debug('Skipping composeWebhook returned null', {
                    teamId: event.team_id,
                    pluginConfigId: pluginConfig.id,
                    eventUuid: event.uuid,
                })
                return
            }
            const request = await trackedFetch(webhook.url, {
                method: webhook.method || 'POST',
                body: JSON.stringify(webhook.body, undefined, 4),
                headers: webhook.headers || { 'Content-Type': 'application/json' },
                timeout: hub.EXTERNAL_REQUEST_TIMEOUT_MS,
            })
            if (request.ok) {
                await hub.appMetrics.queueMetric({
                    teamId: event.team_id,
                    pluginConfigId: pluginConfig.id,
                    category: 'composeWebhook',
                    successes: 1,
                })
            } else {
                hub.statsd?.increment(`${metricName}.ERROR`, metricTags)
                const error = `Fetch to ${webhook.url} failed with ${request.statusText}`
                await processError(hub, pluginConfig, error, event)
                await hub.appMetrics.queueError(
                    {
                        teamId: event.team_id,
                        pluginConfigId: pluginConfig.id,
                        category: 'composeWebhook',
                        failures: 1,
                    },
                    {
                        error,
                        event,
                    }
                )
            }
        } catch (error) {
            hub.statsd?.increment(`${metricName}.ERROR`, metricTags)
            await processError(hub, pluginConfig, error, event)
            await hub.appMetrics.queueError(
                {
                    teamId: event.team_id,
                    pluginConfigId: pluginConfig.id,
                    category: 'composeWebhook',
                    failures: 1,
                },
                {
                    error,
                    event,
                }
            )
        }
        hub.statsd?.timing(metricName, timer, metricTags)
    } finally {
        clearTimeout(timeout)
    }
}

export async function runComposeWebhook(hub: Hub, event: PostHogEvent): Promise<void> {
    // Runs composeWebhook for all plugins for this team in parallel
    const pluginMethodsToRun = await getPluginMethodsForTeam(hub, event.team_id, 'composeWebhook')

    await Promise.all(
        pluginMethodsToRun
            .filter(([, method]) => !!method)
            .map(([pluginConfig, composeWebhook]) =>
                instrument(
                    hub.statsd,
                    {
                        metricName: 'plugin.runComposeWebhook',
                        key: 'plugin',
                        tag: pluginConfig.plugin?.name || '?',
                    },
                    () => runSingleTeamPluginComposeWebhook(hub, event, pluginConfig, composeWebhook)
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
        if (onEvent) {
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
    const teamId = pluginConfig?.team_id
    let shouldQueueAppMetric = false

    try {
        const task = await pluginConfig?.vm?.getTask(taskName, taskType)
        if (!task) {
            throw new Error(
                `Task "${taskName}" not found for plugin "${pluginConfig?.plugin?.name}" with config id ${pluginConfigId}`
            )
        }

        if (!pluginConfig?.enabled) {
            status.info('🚮', 'Skipping job for disabled pluginconfig', {
                taskName: taskName,
                taskType: taskType,
                pluginConfigId: pluginConfigId,
            })
            return
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
    const pluginConfigs = hub.pluginConfigsPerTeam.get(teamId) || []
    if (pluginConfigs.length === 0) {
        return []
    }
    const methodsObtained = await Promise.all(
        pluginConfigs.map(async (pluginConfig) => [pluginConfig, await pluginConfig?.vm?.getVmMethod(method)])
    )
    return methodsObtained as [PluginConfig, VMMethods[M]][]
}
