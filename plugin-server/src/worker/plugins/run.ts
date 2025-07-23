import { Webhook } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginMethodsConcrete, PostIngestionEvent } from '../../types'
import { processError } from '../../utils/db/error'
import {
    convertToOnEventPayload,
    convertToPostHogEvent,
    mutatePostIngestionEventWithElementsList,
} from '../../utils/event'
import { logger } from '../../utils/logger'
import { legacyFetch } from '../../utils/request'
import { WebhookFormatter } from '../ingestion/webhook-formatter'
import { pluginActionMsSummary } from '../metrics'

const PLUGIN_URL_LEGACY_ACTION_WEBHOOK = 'https://github.com/PostHog/legacy-action-webhook'

async function runSingleTeamPluginOnEvent(
    hub: Hub,
    event: PostIngestionEvent,
    pluginConfig: PluginConfig,
    onEvent: PluginMethodsConcrete['onEvent']
): Promise<{ backgroundTask: Promise<any> }> {
    if (!hub.pluginConfigsToSkipElementsParsing?.(pluginConfig.plugin_id)) {
        // Elements parsing can be extremely slow, so we skip it for some plugins that are manually marked as not needing it
        mutatePostIngestionEventWithElementsList(event)
    }

    const onEventPayload = convertToOnEventPayload(event)

    let error: any = null

    // Runs onEvent for a single plugin without any retries
    const timer = new Date()
    try {
        await onEvent(onEventPayload)
    } catch (e) {
        error = e
    }

    pluginActionMsSummary
        .labels(pluginConfig.plugin?.id.toString() ?? '?', 'onEvent', error ? 'error' : 'success')
        .observe(new Date().getTime() - timer.getTime())

    if (!error) {
        return {
            backgroundTask: hub.appMetrics.queueMetric({
                teamId: event.teamId,
                pluginConfigId: pluginConfig.id,
                category: 'onEvent',
                successes: 1,
            }),
        }
    } else {
        return {
            backgroundTask: Promise.all([
                processError(hub, pluginConfig, error, onEventPayload),
                hub.appMetrics.queueError(
                    {
                        teamId: event.teamId,
                        pluginConfigId: pluginConfig.id,
                        category: 'onEvent',
                        failures: 1,
                    },
                    {
                        error,
                        event,
                    }
                ),
            ]),
        }
    }
}

export async function runOnEvent(hub: Hub, event: PostIngestionEvent): Promise<{ backgroundTask: Promise<any> }[]> {
    // Runs onEvent for all plugins for this team in parallel
    const pluginMethodsToRun = await getPluginMethodsForTeam(hub, event.teamId, 'onEvent')

    return await Promise.all(
        pluginMethodsToRun.map(([pluginConfig, onEvent]) =>
            runSingleTeamPluginOnEvent(hub, event, pluginConfig, onEvent)
        )
    )
}

async function runSingleTeamPluginComposeWebhook(
    hub: Hub,
    postIngestionEvent: PostIngestionEvent,
    pluginConfig: PluginConfig,
    composeWebhook: PluginMethodsConcrete['composeWebhook']
): Promise<void> {
    // 1. Calls `composeWebhook` for the plugin, send `composeWebhook` appmetric success/fail if applicable.
    // 2. Send via Rusty-Hook if enabled.
    // 3. Send via `fetch` if Rusty-Hook is not enabled.

    const event = convertToPostHogEvent(postIngestionEvent)
    let maybeWebhook: Webhook | null = null
    try {
        if (pluginConfig.plugin?.url === PLUGIN_URL_LEGACY_ACTION_WEBHOOK) {
            const team = await hub.teamManager.getTeam(event.team_id)

            if (team) {
                const webhookFormatter = new WebhookFormatter({
                    webhookUrl: pluginConfig.config.webhook_url as string,
                    messageFormat: pluginConfig.config.message_format as string,
                    event: postIngestionEvent,
                    team,
                    siteUrl: hub.SITE_URL,
                    // TODO: What about pluginConfig.name ?
                    sourceName: pluginConfig.plugin?.name || 'Unnamed plugin',
                    sourcePath: `/pipeline/destinations/${pluginConfig.id}`,
                })
                maybeWebhook = webhookFormatter.composeWebhook()
            }
        } else {
            maybeWebhook = composeWebhook(event)
        }

        if (!maybeWebhook) {
            // TODO: ideally we'd queryMetric it as skipped, but that's not an option atm
            logger.debug('Skipping composeWebhook returned null', {
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
        logger.warn(
            '⌛',
            `Still running single composeWebhook plugin for team ${event.team_id} for plugin ${pluginConfig.id}`
        )
    }, slowWarningTimeout)
    const timer = new Date()

    try {
        const request = await legacyFetch(webhook.url, {
            method: webhook.method || 'POST',
            body: webhook.body,
            headers: webhook.headers || { 'Content-Type': 'application/json' },
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
    const pluginMethodsToRun = await getPluginMethodsForTeam(hub, event.teamId, 'composeWebhook')

    await Promise.all(
        pluginMethodsToRun.map(([pluginConfig, composeWebhook]) =>
            runSingleTeamPluginComposeWebhook(hub, event, pluginConfig, composeWebhook)
        )
    )
}

async function getPluginMethodsForTeam<M extends keyof PluginMethodsConcrete>(
    hub: Hub,
    teamId: number,
    method: M
): Promise<[PluginConfig, PluginMethodsConcrete[M]][]> {
    const pluginConfigs = hub.pluginConfigsPerTeam.get(teamId) || []
    if (pluginConfigs.length === 0) {
        return []
    }

    const methodsObtained = await Promise.all(
        pluginConfigs.map(async (pluginConfig) => [pluginConfig, await pluginConfig?.instance?.getPluginMethod(method)])
    )

    const methodsObtainedFiltered = methodsObtained.filter(([_, method]) => !!method) as [
        PluginConfig,
        PluginMethodsConcrete[M]
    ][]

    return methodsObtainedFiltered
}
