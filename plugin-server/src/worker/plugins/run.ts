import { PluginEvent, PostHogEvent, ProcessedPluginEvent, Webhook } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginTaskType, VMMethods } from '../../types'
import { processError } from '../../utils/db/error'
import { trackedFetch } from '../../utils/fetch'
import { status } from '../../utils/status'
import { IllegalOperationError } from '../../utils/utils'
import { pluginActionMsSummary } from '../metrics'

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
        const timer = new Date()
        try {
            await onEvent!(event)
            pluginActionMsSummary
                .labels(pluginConfig.plugin?.id.toString() ?? '?', 'onEvent', 'success')
                .observe(new Date().getTime() - timer.getTime())
            await hub.appMetrics.queueMetric({
                teamId: event.team_id,
                pluginConfigId: pluginConfig.id,
                category: 'onEvent',
                successes: 1,
            })
        } catch (error) {
            pluginActionMsSummary
                .labels(pluginConfig.plugin?.id.toString() ?? '?', 'onEvent', 'error')
                .observe(new Date().getTime() - timer.getTime())
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
            .map(([pluginConfig, onEvent]) => runSingleTeamPluginOnEvent(hub, event, pluginConfig, onEvent))
    )
}

async function runSingleTeamPluginComposeWebhook(
    hub: Hub,
    event: PostHogEvent,
    pluginConfig: PluginConfig,
    composeWebhook: any
): Promise<void> {
    // 1. Calls `composeWebhook` for the plugin, send `composeWebhook` appmetric success/fail if applicable.
    // 2. Send via Rusty-Hook if enabled.
    // 3. Send via `fetch` if Rusty-Hook is not enabled.

    let maybeWebhook: Webhook | null = null
    try {
        maybeWebhook = await composeWebhook!(event)
        if (!maybeWebhook) {
            // TODO: ideally we'd queryMetric it as skipped, but that's not an option atm
            status.debug('Skipping composeWebhook returned null', {
                teamId: event.team_id,
                pluginConfigId: pluginConfig.id,
                eventUuid: event.uuid,
            })

            // Nothing to send below, exit.
            return
        }

        await hub.appMetrics.queueMetric({
            teamId: event.team_id,
            pluginConfigId: pluginConfig.id,
            category: 'composeWebhook',
            successes: 1,
        })
    } catch (error) {
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

        // Nothing to send below, exit.
        return
    }

    const webhook: Webhook = maybeWebhook!

    const enqueuedInRustyHook = await hub.rustyHook.enqueueIfEnabledForTeam({
        webhook,
        teamId: event.team_id,
        pluginId: pluginConfig.plugin_id,
        pluginConfigId: pluginConfig.id,
    })

    if (enqueuedInRustyHook) {
        // Rusty-Hook handles it from here, so we're done.
        return
    }

    // Old-style `fetch` send, used for on-prem.
    const slowWarningTimeout = hub.EXTERNAL_REQUEST_TIMEOUT_MS * 0.7
    const timeout = setTimeout(() => {
        status.warn(
            '⌛',
            `Still running single composeWebhook plugin for team ${event.team_id} for plugin ${pluginConfig.id}`
        )
    }, slowWarningTimeout)
    const timer = new Date()

    try {
        const request = await trackedFetch(webhook.url, {
            method: webhook.method || 'POST',
            body: webhook.body,
            headers: webhook.headers || { 'Content-Type': 'application/json' },
            timeout: hub.EXTERNAL_REQUEST_TIMEOUT_MS,
        })
        if (request.ok) {
            pluginActionMsSummary
                .labels(pluginConfig.plugin?.id.toString() ?? '?', 'composeWebhook', 'success')
                .observe(new Date().getTime() - timer.getTime())
            await hub.appMetrics.queueMetric({
                teamId: event.team_id,
                pluginConfigId: pluginConfig.id,
                category: 'webhook',
                successes: 1,
            })
        } else {
            pluginActionMsSummary
                .labels(pluginConfig.plugin?.id.toString() ?? '?', 'composeWebhook', 'error')
                .observe(new Date().getTime() - timer.getTime())
            const error = `Fetch to ${webhook.url} failed with ${request.statusText}`
            await processError(hub, pluginConfig, error, event)
            await hub.appMetrics.queueError(
                {
                    teamId: event.team_id,
                    pluginConfigId: pluginConfig.id,
                    category: 'webhook',
                    failures: 1,
                },
                {
                    error,
                    event,
                }
            )
        }
    } catch (error) {
        pluginActionMsSummary
            .labels(pluginConfig.plugin?.id.toString() ?? '?', 'composeWebhook', 'error')
            .observe(new Date().getTime() - timer.getTime())
        await processError(hub, pluginConfig, error, event)
        await hub.appMetrics.queueError(
            {
                teamId: event.team_id,
                pluginConfigId: pluginConfig.id,
                category: 'webhook',
                failures: 1,
            },
            {
                error,
                event,
            }
        )
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
                runSingleTeamPluginComposeWebhook(hub, event, pluginConfig, composeWebhook)
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
                returnedEvent = (await processEvent(returnedEvent!)) || null
                if (returnedEvent && returnedEvent.team_id !== teamId) {
                    returnedEvent.team_id = teamId
                    throw new IllegalOperationError('Plugin tried to change event.team_id')
                }
                pluginsSucceeded.push(pluginIdentifier)
                pluginActionMsSummary
                    .labels(pluginConfig.plugin?.id.toString() ?? '?', 'processEvent', 'success')
                    .observe(new Date().getTime() - timer.getTime())
                await hub.appMetrics.queueMetric({
                    teamId,
                    pluginConfigId: pluginConfig.id,
                    category: 'processEvent',
                    successes: 1,
                })
            } catch (error) {
                await processError(hub, pluginConfig, error, returnedEvent)
                pluginActionMsSummary
                    .labels(pluginConfig.plugin?.id.toString() ?? '?', 'processEvent', 'error')
                    .observe(new Date().getTime() - timer.getTime())
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
        response = await (payload ? task?.exec(payload) : task?.exec())

        pluginActionMsSummary
            .labels(String(pluginConfig?.plugin?.id), 'task', 'success')
            .observe(new Date().getTime() - timer.getTime())
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

        pluginActionMsSummary
            .labels(String(pluginConfig?.plugin?.id), 'task', 'error')
            .observe(new Date().getTime() - timer.getTime())
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
