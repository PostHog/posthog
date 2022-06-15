import { ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig } from '../types'
import { processError } from '../utils/db/error'

export function getNextRetryMs(baseMs: number, multiplier: number, attempt: number): number {
    return baseMs * multiplier ** (attempt - 1)
}

export interface RetriableFunctionOptions {
    event: ProcessedPluginEvent
    tryFn: () => Promise<void>
    catchFn?: (error: Error) => Promise<void>
    finallyFn?: (attempts: number) => Promise<void>
    maxAttempts?: number
    retryBaseMs?: number
    retryMultiplier?: number
}

async function iterateRetryLoop(
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
    }: RetriableFunctionOptions,
    attempt = 1
): Promise<void> {
    const teamIdString = event.team_id.toString()
    let nextIterationTimeout: NodeJS.Timeout | undefined
    try {
        await tryFn()
    } catch (error) {
        if (error instanceof RetryError) {
            error._attempt = attempt
            error._maxAttempts = maxAttempts
        }
        if (error instanceof RetryError && attempt < maxAttempts) {
            const nextRetryMs = getNextRetryMs(retryBaseMs, retryMultiplier, attempt)
            hub.statsd?.increment(`plugin.${tag}.RETRY`, {
                plugin: pluginConfig.plugin?.name ?? '?',
                teamId: teamIdString,
                attempt: attempt.toString(),
            })
            nextIterationTimeout = setTimeout(() => {
                // This is intentionally voided so that attempts beyond the first one don't stall the event queue
                void iterateRetryLoop(
                    tag,
                    hub,
                    pluginConfig,
                    {
                        event,
                        tryFn,
                        catchFn,
                        finallyFn,
                        maxAttempts,
                        retryBaseMs,
                        retryMultiplier,
                    },
                    attempt + 1
                )
            }, nextRetryMs)
        } else {
            await catchFn?.(error)
            await processError(hub, pluginConfig, error, event)
            hub.statsd?.increment(`plugin.${tag}.ERROR`, {
                plugin: pluginConfig.plugin?.name ?? '?',
                teamId: teamIdString,
                attempt: attempt.toString(),
            })
        }
    }
    if (!nextIterationTimeout) {
        await finallyFn?.(attempt)
    }
}

/** Run function with `RetryError` handling. */
export async function runRetriableFunction(
    tag: string,
    hub: Hub,
    pluginConfig: PluginConfig,
    options: RetriableFunctionOptions
): Promise<void> {
    const timer = new Date()
    await iterateRetryLoop(tag, hub, pluginConfig, options)
    hub.statsd?.timing(`plugin.${tag}`, timer, {
        plugin: pluginConfig.plugin?.name ?? '?',
        teamId: options.event.team_id.toString(),
    })
}
