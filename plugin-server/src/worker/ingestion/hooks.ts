import { Histogram } from 'prom-client'

import { Action, Hook, HookPayload, PostIngestionEvent, Team } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { convertToHookPayload } from '../../utils/event'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { legacyFetch } from '../../utils/request'
import { TeamManager } from '../../utils/team-manager'
import { RustyHook } from '../../worker/rusty-hook'
import { AppMetric, AppMetrics } from './app-metrics'
import { WebhookFormatter } from './webhook-formatter'

export const webhookProcessStepDuration = new Histogram({
    name: 'webhook_process_event_duration',
    help: 'Processing step latency to during webhooks processing, per tag',
    labelNames: ['tag'],
})

export async function instrumentWebhookStep<T>(tag: string, run: () => Promise<T>): Promise<T> {
    const end = webhookProcessStepDuration
        .labels({
            tag: tag,
        })
        .startTimer()
    const res = await run()
    end()
    return res
}

export class HookCommander {
    postgres: PostgresRouter
    teamManager: TeamManager
    rustyHook: RustyHook
    appMetrics: AppMetrics
    siteUrl: string
    /** Hook request timeout in ms. */
    EXTERNAL_REQUEST_TIMEOUT: number

    constructor(
        postgres: PostgresRouter,
        teamManager: TeamManager,
        rustyHook: RustyHook,
        appMetrics: AppMetrics,
        timeout: number
    ) {
        this.postgres = postgres
        this.teamManager = teamManager
        if (process.env.SITE_URL) {
            this.siteUrl = process.env.SITE_URL
        } else {
            logger.warn('⚠️', 'SITE_URL env is not set for webhooks')
            this.siteUrl = ''
        }
        this.rustyHook = rustyHook
        this.appMetrics = appMetrics
        this.EXTERNAL_REQUEST_TIMEOUT = timeout
    }

    public async findAndFireHooks(event: PostIngestionEvent, actionMatches: Action[]): Promise<void> {
        logger.debug('🔍', `Looking for hooks to fire for event "${event.event}"`)
        if (!actionMatches.length) {
            logger.debug('🔍', `No hooks to fire for event "${event.event}"`)
            return
        }
        logger.debug('🔍', `Found ${actionMatches.length} matching actions`)

        const team = await this.teamManager.getTeam(event.teamId)

        if (!team) {
            return
        }

        const webhookUrl = team.slack_incoming_webhook

        if (webhookUrl) {
            await instrumentWebhookStep('postWebhook', async () => {
                const webhookRequests = actionMatches
                    .filter((action) => action.post_to_slack)
                    .map((action) => this.postWebhook(event, action, team))
                await Promise.all(webhookRequests).catch((error) =>
                    captureException(error, { tags: { team_id: event.teamId } })
                )
            })
        }

        if (await this.teamManager.hasAvailableFeature(team.id, 'zapier')) {
            await instrumentWebhookStep('postRestHook', async () => {
                const restHooks = actionMatches.flatMap((action) => action.hooks.map((hook) => ({ hook, action })))

                if (restHooks.length > 0) {
                    const restHookRequests = restHooks.map(({ hook, action }) =>
                        this.postWebhook(event, action, team, hook)
                    )
                    await Promise.all(restHookRequests).catch((error) =>
                        captureException(error, { tags: { team_id: event.teamId } })
                    )
                }
            })
        }
    }

    private formatMessage(
        webhookUrl: string,
        messageFormat: string,
        action: Action,
        event: PostIngestionEvent,
        team: Team
    ): Record<string, any> {
        const endTimer = webhookProcessStepDuration.labels('messageFormatting').startTimer()
        try {
            const webhookFormatter = new WebhookFormatter({
                webhookUrl,
                messageFormat,
                event,
                team,
                siteUrl: this.siteUrl,
                sourceName: action.name ?? 'Unamed action',
                sourcePath: `/action/${action.id}`,
            })
            return webhookFormatter.generateWebhookPayload()
        } finally {
            endTimer()
        }
    }

    public async postWebhook(event: PostIngestionEvent, action: Action, team: Team, hook?: Hook): Promise<void> {
        // Used if no hook is provided
        const defaultWebhookUrl = team.slack_incoming_webhook
        // -2 is hardcoded to mean webhooks, -1 for resthooks
        const SPECIAL_CONFIG_ID = hook ? -1 : -2
        const partialMetric: AppMetric = {
            teamId: event.teamId,
            pluginConfigId: SPECIAL_CONFIG_ID,
            category: 'webhook',
            successes: 1,
        }

        const url = hook ? hook.target : defaultWebhookUrl
        let body: any

        if (!url) {
            // NOTE: Typically this is covered by the caller already
            return
        }

        if (!hook) {
            const messageFormat = action.slack_message_format || '[action.name] was triggered by [person]'
            body = this.formatMessage(url, messageFormat, action, event, team)
        } else {
            const hookBody: HookPayload = {
                hook: { id: hook.id, event: hook.event, target: hook.target },
                data: convertToHookPayload(event),
            }

            body = hookBody
        }

        const enqueuedInRustyHook = await this.rustyHook.enqueueIfEnabledForTeam({
            webhook: {
                url,
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body, undefined, 4),
            },
            teamId: event.teamId,
            pluginId: SPECIAL_CONFIG_ID,
            pluginConfigId: SPECIAL_CONFIG_ID, // -2 is hardcoded to mean webhooks
        })

        if (enqueuedInRustyHook) {
            // Rusty-Hook handles it from here, so we're done.
            return
        }

        const slowWarningTimeout = this.EXTERNAL_REQUEST_TIMEOUT * 0.7
        const timeout = setTimeout(() => {
            logger.warn(
                '⌛',
                `Posting Webhook slow. Timeout warning after ${slowWarningTimeout / 1000} sec! url=${url} team_id=${
                    team.id
                } event_id=${event.eventUuid}`
            )
        }, slowWarningTimeout)

        logger.debug('⚠️', `Firing webhook ${url} for team ${team.id}`)

        try {
            await instrumentWebhookStep('fetch', async () => {
                const request = await legacyFetch(url, {
                    method: 'POST',
                    body: JSON.stringify(body, null, 4),
                    headers: { 'Content-Type': 'application/json' },
                })
                // special handling for hooks
                if (hook && request.status === 410) {
                    // Delete hook on our side if it's gone on Zapier's
                    await this.deleteRestHook(hook.id)
                }
                if (!request.ok) {
                    logger.warn('⚠️', `HTTP status ${request.status} for team ${team.id}`)
                    await this.appMetrics.queueError(
                        {
                            ...partialMetric,
                            failures: 1,
                        },
                        {
                            error: `Request failed with HTTP status ${request.status}`,
                            event,
                        }
                    )
                } else {
                    await this.appMetrics.queueMetric({
                        ...partialMetric,
                        successes: 1,
                    })
                }
            })
        } catch (error) {
            await this.appMetrics.queueError(
                {
                    ...partialMetric,
                    failures: 1,
                },
                {
                    error,
                    event,
                }
            )
            throw error
        } finally {
            clearTimeout(timeout)
        }
    }

    private async deleteRestHook(hookId: Hook['id']): Promise<void> {
        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `DELETE FROM ee_hook WHERE id = $1`,
            [hookId],
            'deleteRestHook'
        )
    }
}
