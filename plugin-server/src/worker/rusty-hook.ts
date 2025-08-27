// eslint-disable-next-line no-restricted-imports
import fetch from 'node-fetch'

import { Webhook } from '@posthog/plugin-scaffold'

import { buildIntegerMatcher } from '../config/config'
import { PluginsServerConfig, ValueMatcher } from '../types'
import { isProdEnv } from '../utils/env-utils'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'
import { raiseIfUserProvidedUrlUnsafe } from '../utils/request'
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
        created_at: string
    }
}

export class RustyHook {
    private enabledForTeams: ValueMatcher<number>

    constructor(
        private serverConfig: Pick<
            PluginsServerConfig,
            | 'RUSTY_HOOK_URL'
            | 'HOG_HOOK_URL'
            | 'RUSTY_HOOK_FOR_TEAMS'
            | 'RUSTY_HOOK_ROLLOUT_PERCENTAGE'
            | 'EXTERNAL_REQUEST_TIMEOUT_MS'
        >
    ) {
        this.enabledForTeams = buildIntegerMatcher(serverConfig.RUSTY_HOOK_FOR_TEAMS, true)
    }

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
        const enabledByRolloutPercentage = (teamId % 1000) / 1000 < this.serverConfig.RUSTY_HOOK_ROLLOUT_PERCENTAGE
        if (!enabledByRolloutPercentage && !this.enabledForTeams(teamId)) {
            return false
        }

        webhook.method ??= 'POST'
        webhook.headers ??= {}

        if (isProdEnv()) {
            await raiseIfUserProvidedUrlUnsafe(webhook.url)
        }

        const rustyWebhookPayload: RustyWebhookPayload = {
            parameters: webhook,
            metadata: {
                team_id: teamId,
                plugin_id: pluginId,
                plugin_config_id: pluginConfigId,
                created_at: new Date().toISOString(),
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
                const response = await fetch(this.serverConfig.RUSTY_HOOK_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body,

                    // Sure, it's not an external request, but we should have a timeout and this is as
                    // good as any.
                    timeout: this.serverConfig.EXTERNAL_REQUEST_TIMEOUT_MS,
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
                logger.error('🔴', 'Webhook enqueue to rusty-hook failed', { error, redactedWebhook, attempt })
                captureException(error, { extra: { redactedWebhook } })
            }

            const delayMs = Math.min(2 ** (attempt - 1) * RUSTY_HOOK_BASE_DELAY_MS, MAX_RUSTY_HOOK_DELAY_MS)
            await sleep(delayMs)
        }

        return true
    }

    public async enqueueForHog(payload: string): Promise<boolean> {
        // This is a temporary copy of `enqueueIfEnabledForTeam` above for Hog fetches because the
        // API differs. It will likely be replaced with a Kafka topic soon.

        // We attempt to enqueue into the rusty-hook service until we succeed. This is deliberatly
        // designed to block up the consumer if rusty-hook is down or if we deploy code that
        // sends malformed requests. The entire purpose of rusty-hook is to reliably deliver webhooks,
        // so we'd rather leave items in the Kafka topic until we manage to get them into rusty-hook.
        let attempt = 0
        while (true) {
            try {
                attempt += 1
                const response = await fetch(this.serverConfig.HOG_HOOK_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: payload,

                    // Sure, it's not an external request, but we should have a timeout and this is as
                    // good as any.
                    timeout: this.serverConfig.EXTERNAL_REQUEST_TIMEOUT_MS,
                })

                if (response.ok) {
                    // Success, exit the loop.
                    break
                }

                // TODO: Remove this after more thorough testing of hoghooks. For now, we don't want
                // to choke up Hog ingestion if something is wrong with our payload or with
                // rusty-hook. By returning `false`, we leave it to the `AsyncFunctionExecutor` to
                // call `fetch` inline.
                if (response.status >= 400) {
                    const message = 'Hoghook enqueue failed with an HTTP Error'
                    captureException(message, {
                        extra: {
                            status: response.status,
                            statusText: response.statusText,
                        },
                    })
                    logger.error('🔴', message, {
                        status: response.status,
                        statusText: response.statusText,
                        payload,
                    })
                    return false
                }

                // Throw to unify error handling below.
                throw new Error(
                    `Hoghook enqueue returned ${response.status} ${response.statusText}: ${await response.text()}`
                )
            } catch (error) {
                logger.error('🔴', 'Hoghook enqueue to rusty-hook for Hog failed', { error, attempt })
                captureException(error)
            }

            const delayMs = Math.min(2 ** (attempt - 1) * RUSTY_HOOK_BASE_DELAY_MS, MAX_RUSTY_HOOK_DELAY_MS)
            await sleep(delayMs)
        }

        return true
    }
}
