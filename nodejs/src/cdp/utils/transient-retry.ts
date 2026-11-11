import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

export const transientLookupRetryCounter = new Counter({
    name: 'cdp_transient_lookup_retries_total',
    help: 'Invocations that a transient error in a lookup they need sent back to the queue or failed',
    labelNames: ['lookup', 'outcome'],
})

export type TransientRetryPolicy = {
    retries: number
    backoffBaseMs: number
    backoffMaxMs: number
}

export const isTransientError = (error: unknown): boolean =>
    (error as { isRetriable?: unknown } | null | undefined)?.isRetriable === true

export function transientRetryAt(attempts: number, policy: TransientRetryPolicy): DateTime | null {
    if (attempts >= policy.retries) {
        return null
    }
    const backoffMs = Math.min(
        policy.backoffBaseMs * attempts + Math.floor(Math.random() * policy.backoffBaseMs),
        policy.backoffMaxMs
    )
    return DateTime.utc().plus({ milliseconds: backoffMs })
}
