import { ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig } from '../types'
import { processError } from '../utils/db/error'
import { delay } from '../utils/utils'

export function getNextRetryMs(baseMs: number, multiplier: number, attempt: number): number {
    return baseMs * multiplier ** (attempt - 1)
}

export interface RetriableFunctionOptions {
    event: ProcessedPluginEvent
    tryFn: () => Promise<void>
    catchFn?: (error: Error) => Promise<void>
    finallyFn?: () => Promise<void>
    maxAttempts?: number
    retryBaseMs?: number
    retryMultiplier?: number
}

/** Run function with `RetryError` handling. Returns the number of attempts made. */
export async function runRetriableFunction(
    tag: string,
    hub: Hub,
    pluginConfig: PluginConfig,
    {
        event,
        tryFn,
        catchFn,
        finallyFn,
        maxAttempts = 5,
        retryBaseMs = 5000,
        retryMultiplier = 2,
    }: RetriableFunctionOptions
): Promise<number> {
    const timer = new Date()
    let attempt = 0
    const teamIdString = event.team_id.toString()
    while (true) {
        attempt++
        let nextRetryMs: number
        try {
            await tryFn()
            break
        } catch (error) {
            if (error instanceof RetryError) {
                error._attempt = attempt
                error._maxAttempts = maxAttempts
            }
            if (error instanceof RetryError && attempt < maxAttempts) {
                nextRetryMs = getNextRetryMs(retryBaseMs, retryMultiplier, attempt)
                hub.statsd?.increment(`plugin.${tag}.RETRY`, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: teamIdString,
                    attempt: attempt.toString(),
                })
            } else {
                await catchFn?.(error)
                await processError(hub, pluginConfig, error, event)
                hub.statsd?.increment(`plugin.${tag}.ERROR`, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: teamIdString,
                    attempt: attempt.toString(),
                })
                break
            }
        }
        await delay(nextRetryMs)
    }
    await finallyFn?.()
    hub.statsd?.timing(`plugin.${tag}`, timer, {
        plugin: pluginConfig.plugin?.name ?? '?',
        teamId: teamIdString,
    })
    return attempt
}
