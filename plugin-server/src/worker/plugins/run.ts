import { PluginEvent, PostHogEvent, ProcessedPluginEvent, Webhook } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import fetch from 'node-fetch'
import { Summary } from 'prom-client'

import { Hub, PluginConfig, PluginTaskType, VMMethods } from '../../types'
import { processError } from '../../utils/db/error'
import { trackedFetch } from '../../utils/fetch'
import { status } from '../../utils/status'
import { IllegalOperationError, sleep } from '../../utils/utils'

const pluginActionMsSummary = new Summary({
    name: 'plugin_action_ms',
    help: 'Time to run plugin action',
    labelNames: ['plugin_id', 'action', 'status'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

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

const RUSTY_HOOK_BASE_DELAY_MS = 100
const MAX_RUSTY_HOOK_DELAY_MS = 30_000

interface RustyWebhookPayload {
    parameters: Webhook
    metadata: {
        team_id: number
        plugin_id: number
        plugin_config_id: number
    }
}

async function enqueueInRustyHook(hub: Hub, webhook: Webhook, pluginConfig: PluginConfig) {
    webhook.method ??= 'POST'
    webhook.headers ??= {}

    const rustyWebhookPayload: RustyWebhookPayload = {
        parameters: webhook,
        metadata: {
            team_id: pluginConfig.team_id,
            plugin_id: pluginConfig.plugin_id,
            plugin_config_id: pluginConfig.id,
        },
    }
    const body = JSON.stringify(rustyWebhookPayload, undefined, 4)

    // We attempt to enqueue into the rusty-hook service until we succeed. This is deliberatly
    // designed to block up the consumer if rusty-hook is down or if we deploy code that
    // sends malformed requests. The entire purpose of rusty-hook is to reliably deliver webhooks,
    // so we'd rather leave items in the Kafka topic until we manage to get them into rusty-hook.
    let attempt = 0
    while (true) {
        const timer = new Date()
        try {
            attempt += 1
            const response = await fetch(hub.RUSTY_HOOK_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body,

                // Sure, it's not an external request, but we should have a timeout and this is as
                // good as any.
                timeout: hub.EXTERNAL_REQUEST_TIMEOUT_MS,
            })

            if (response.ok) {
                // Success, exit the loop.
                pluginActionMsSummary
                    .labels(pluginConfig.plugin_id.toString(), 'enqueueRustyHook', 'success')
                    .observe(new Date().getTime() - timer.getTime())

                break
            }

            // Throw to unify error handling below.
            throw new Error(`rusty-hook returned ${response.status} ${response.statusText}: ${await response.text()}`)
        } catch (error) {
            pluginActionMsSummary
                .labels(pluginConfig.plugin_id.toString(), 'enqueueRustyHook', 'error')
                .observe(new Date().getTime() - timer.getTime())

            const redactedWebhook = {
                parameters: { ...rustyWebhookPayload.parameters, body: '<redacted>' },
                metadata: rustyWebhookPayload.metadata,
            }
            status.error('🔴', 'Webhook enqueue to rusty-hook failed', { error, redactedWebhook, attempt })
            Sentry.captureException(error, { extra: { redactedWebhook } })
        }

        const delayMs = Math.min(2 ** (attempt - 1) * RUSTY_HOOK_BASE_DELAY_MS, MAX_RUSTY_HOOK_DELAY_MS)
        await sleep(delayMs)
    }
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

            if (hub.rustyHookForTeams?.(event.team_id)) {
                return await enqueueInRustyHook(hub, webhook, pluginConfig)
            }

            const request = await trackedFetch(webhook.url, {
                method: webhook.method || 'POST',
                body: JSON.stringify(webhook.body, undefined, 4),
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
                    category: 'composeWebhook',
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
            pluginActionMsSummary
                .labels(pluginConfig.plugin?.id.toString() ?? '?', 'composeWebhook', 'error')
                .observe(new Date().getTime() - timer.getTime())
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
