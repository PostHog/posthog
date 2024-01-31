import { Webhook } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import fetch from 'node-fetch'

import { ValueMatcher } from '../types'
import { isProdEnv } from '../utils/env-utils'
import { raiseIfUserProvidedUrlUnsafe } from '../utils/fetch'
import { status } from '../utils/status'
import { sleep } from '../utils/utils'
import { pluginActionMsSummary } from './metrics'

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

export class RustyHook {
    constructor(
        private enabledForTeams: ValueMatcher<number>,
        private rolloutPercentage: number,
        private serviceUrl: string,
        private requestTimeoutMs: number
    ) {}

    public async enqueueIfEnabledForTeam({
        webhook,
        teamId,
        pluginId,
        pluginConfigId,
    }: {
        webhook: Webhook
        teamId: number
        pluginId: number
        pluginConfigId: number
    }): Promise<boolean> {
        // A simple and blunt rollout that just uses the last digits of the Team ID as a stable
        // selection against the `rolloutPercentage`.
        const enabledByRolloutPercentage = (teamId % 1000) / 1000 < this.rolloutPercentage
        if (!enabledByRolloutPercentage && !this.enabledForTeams(teamId)) {
            return false
        }

        webhook.method ??= 'POST'
        webhook.headers ??= {}

        if (isProdEnv() && !process.env.NODE_ENV?.includes('functional-tests')) {
            await raiseIfUserProvidedUrlUnsafe(webhook.url)
        }

        const rustyWebhookPayload: RustyWebhookPayload = {
            parameters: webhook,
            metadata: {
                team_id: teamId,
                plugin_id: pluginId,
                plugin_config_id: pluginConfigId,
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
                const response = await fetch(this.serviceUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body,

                    // Sure, it's not an external request, but we should have a timeout and this is as
                    // good as any.
                    timeout: this.requestTimeoutMs,
                })

                if (response.ok) {
                    // Success, exit the loop.
                    pluginActionMsSummary
                        .labels(pluginId.toString(), 'enqueueRustyHook', 'success')
                        .observe(new Date().getTime() - timer.getTime())

                    break
                }

                // Throw to unify error handling below.
                throw new Error(
                    `rusty-hook returned ${response.status} ${response.statusText}: ${await response.text()}`
                )
            } catch (error) {
                pluginActionMsSummary
                    .labels(pluginId.toString(), 'enqueueRustyHook', 'error')
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

        return true
    }
}
