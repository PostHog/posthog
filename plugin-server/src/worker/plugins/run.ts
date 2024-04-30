import { PluginEvent, ProcessedPluginEvent, Webhook } from '@posthog/plugin-scaffold'

import { Action, Hub, PluginConfig, PluginTaskType, PostIngestionEvent, VMMethodsConcrete } from '../../types'
import { processError } from '../../utils/db/error'
import { convertToPostHogEvent } from '../../utils/event'
import { trackedFetch } from '../../utils/fetch'
import { status } from '../../utils/status'
import { IllegalOperationError } from '../../utils/utils'
import { ActionWebhookFormatter } from '../ingestion/action-webhook-formatter'
import { pluginActionMsSummary } from '../metrics'

async function runSingleTeamPluginOnEvent(
    hub: Hub,
    event: ProcessedPluginEvent,
    pluginConfig: PluginConfig,
    onEvent: VMMethodsConcrete['onEvent']
): Promise<void> {
    const timeout = setTimeout(() => {
        status.warn('⌛', `Still running single onEvent plugin for team ${event.team_id} for plugin ${pluginConfig.id}`)
    }, 10 * 1000) // 10 seconds
    try {
        // Runs onEvent for a single plugin without any retries
        const timer = new Date()
        try {
            await onEvent(event)
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
        pluginMethodsToRun.map(([pluginConfig, onEvent]) =>
            runSingleTeamPluginOnEvent(hub, event, pluginConfig, onEvent)
        )
    )
}

async function runSingleTeamPluginComposeWebhook(
    hub: Hub,
    postIngestionEvent: PostIngestionEvent,
    pluginConfig: PluginConfig,
    composeWebhook: VMMethodsConcrete['composeWebhook']
): Promise<void> {
    const event = convertToPostHogEvent(postIngestionEvent)
    // 1. Calls `composeWebhook` for the plugin, send `composeWebhook` appmetric success/fail if applicable.
    // 2. Send via Rusty-Hook if enabled.
    // 3. Send via `fetch` if Rusty-Hook is not enabled.

    let maybeWebhook: Webhook | null = null
    try {
        // TODO: This was async before but the type is not async - was it supposed to be??
        maybeWebhook = composeWebhook(event)
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

    const webhook: Webhook = maybeWebhook

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

export async function runComposeWebhook(hub: Hub, event: PostIngestionEvent): Promise<void> {
    // Runs composeWebhook for all plugins for this team in parallel
    let pluginMethodsToRun = await getPluginMethodsForTeam(hub, event.teamId, 'composeWebhook')
    pluginMethodsToRun = await filterPluginMethodsForActionMatches(hub, event, pluginMethodsToRun)

    pluginMethodsToRun = pluginMethodsToRun.concat(await getLegacyActionWebhookPluginsForTeam(hub, event))

    // Inject special plugin!
    // Here we load the special "LegacyActionWebhook" plugin which is actually run in memory

    await Promise.all(
        pluginMethodsToRun.map(([pluginConfig, composeWebhook]) =>
            runSingleTeamPluginComposeWebhook(hub, event, pluginConfig, composeWebhook)
        )
    )
}

export async function runProcessEvent(hub: Hub, event: PluginEvent): Promise<PluginEvent | null> {
    const teamId = event.team_id

    // runProcessEvent handles both `processEvent` and `onEvent` for plugins.
    const pluginConfigs = hub.pluginConfigsPerTeam.get(teamId) || []
    const pluginConfigsWithMethods = await Promise.all(
        pluginConfigs.map(async (pluginConfig) => ({
            pluginConfig,
            onEvent: await pluginConfig?.vm?.getOnEvent(),
            processEvent: await pluginConfig?.vm?.getVmMethod('processEvent'),
        }))
    )

    let returnedEvent: PluginEvent | null = event

    const pluginsSucceeded: string[] = event.properties?.$plugins_succeeded || []
    const pluginsFailed = event.properties?.$plugins_failed || []
    const pluginsDeferred = []
    const pluginsAlreadyProcessed = new Set([...pluginsSucceeded, ...pluginsFailed])

    for (const { pluginConfig, onEvent, processEvent } of pluginConfigsWithMethods) {
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

async function getPluginMethodsForTeam<M extends keyof VMMethodsConcrete>(
    hub: Hub,
    teamId: number,
    method: M
): Promise<[PluginConfig, VMMethodsConcrete[M]][]> {
    const pluginConfigs = hub.pluginConfigsPerTeam.get(teamId) || []
    if (pluginConfigs.length === 0) {
        return []
    }

    const methodsObtained = await Promise.all(
        pluginConfigs.map(async (pluginConfig) => [pluginConfig, await pluginConfig?.vm?.getVmMethod(method)])
    )

    const methodsObtainedFiltered = methodsObtained.filter(([_, method]) => !!method) as [
        PluginConfig,
        VMMethodsConcrete[M]
    ][]

    return methodsObtainedFiltered
}

async function getLegacyActionWebhookPluginsForTeam(
    hub: Hub,
    event: PostIngestionEvent
): Promise<[PluginConfig, () => Webhook | null][]> {
    const pluginConfigs = hub.pluginConfigsPerTeam.get(event.teamId) || []
    if (pluginConfigs.length === 0) {
        return []
    }

    const filteredList: [PluginConfig, () => Webhook | null][] = []

    await Promise.all(
        pluginConfigs
            // TODO: We probably want a stronger check than just the plugin name...
            .map(async (pluginConfig) => {
                if (pluginConfig.plugin?.name !== 'Action Webhook' || !pluginConfig.match_action_id) {
                    return
                }

                const matchedAction = await getActionMatchingPluginConfigs(hub, pluginConfig, event)
                const team = await hub.teamManager.fetchTeam(event.teamId)

                if (!matchedAction || !team) {
                    return
                }

                filteredList.push([
                    pluginConfig,
                    () => {
                        // TODO: Fix the forced conversion here
                        const actionWebhookFormatter = new ActionWebhookFormatter(
                            pluginConfig.config.webhook_url as string,
                            pluginConfig.config.message_format as string,
                            matchedAction,
                            event,
                            team,
                            hub.SITE_URL || ''
                        )
                        return actionWebhookFormatter.composeWebhook()
                    },
                ])
            })
    )

    return filteredList
}

async function filterPluginMethodsForActionMatches<T>(
    hub: Hub,
    event: PostIngestionEvent,
    pluginMethods: [PluginConfig, T][]
): Promise<[PluginConfig, T][]> {
    const filteredList: [PluginConfig, T][] = []

    await Promise.all(
        pluginMethods.map(async ([pluginConfig, method]) => {
            if (pluginConfig.match_action_id) {
                const matchedAction = await getActionMatchingPluginConfigs(hub, pluginConfig, event)
                if (!matchedAction) {
                    return
                }
            }
            filteredList.push([pluginConfig, method])
        })
    )

    return filteredList
}

async function getActionMatchingPluginConfigs(
    hub: Hub,
    pluginConfig: PluginConfig,
    event: PostIngestionEvent
): Promise<Action | null> {
    if (!pluginConfig.match_action_id) {
        return null
    }
    const relatedAction = hub.actionMatcher.getActionById(event.teamId, pluginConfig.match_action_id)

    if (!relatedAction) {
        // TODO: Is this what we want to do here?
        status.error('🔴', 'Could not find action for PluginConfig!', {
            pluginConfigId: pluginConfig.id,
            teamId: event.teamId,
        })

        return null
    }

    const matched = await hub.actionMatcher.checkAction(event, relatedAction)

    return matched ? relatedAction : null
}
