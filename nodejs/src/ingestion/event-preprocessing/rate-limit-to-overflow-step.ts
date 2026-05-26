import { EventHeaders, PipelineEvent } from '../../types'
import { OVERFLOW_OUTPUT, OverflowOutput } from '../common/outputs'
import { COOKIELESS_SENTINEL_VALUE } from '../cookieless/cookieless-manager'
import { PipelineResult, ok, redirect } from '../pipelines/results'
import { OverflowEventBatch, OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'

// `headers.distinct_id` is set by capture from Kafka headers and is never mutated by the
// pipeline. For cookieless events it stays equal to COOKIELESS_SENTINEL_VALUE even after the
// cookieless step has rewritten `event.distinct_id` to a hashed value — so it's the reliable
// indicator of "this is a cookieless event" at any point in the pipeline.

interface KeyDerivation {
    token: string
    distinctId: string
}

async function applyOverflowRedirect<T extends { headers: EventHeaders }>(
    inputs: T[],
    overflowRedirectService: OverflowRedirectService | undefined,
    preservePartitionLocality: boolean,
    deriveKey: (input: T) => KeyDerivation | null
): Promise<PipelineResult<T, OverflowOutput>[]> {
    if (!overflowRedirectService) {
        return inputs.map((input) => ok(input))
    }

    const perInputKeys: (string | null)[] = []
    const keyStats = new Map<string, { token: string; distinctId: string; count: number; firstTimestamp: number }>()

    for (const input of inputs) {
        const derived = deriveKey(input)
        if (!derived) {
            perInputKeys.push(null)
            continue
        }

        const eventKey = `${derived.token}:${derived.distinctId}`
        perInputKeys.push(eventKey)

        const timestamp = input.headers.now?.getTime() ?? Date.now()
        const existing = keyStats.get(eventKey)
        if (existing) {
            existing.count++
        } else {
            keyStats.set(eventKey, { ...derived, count: 1, firstTimestamp: timestamp })
        }
    }

    if (keyStats.size === 0) {
        return inputs.map((input) => ok(input))
    }

    const batches: OverflowEventBatch[] = Array.from(keyStats.values()).map(
        ({ token, distinctId, count, firstTimestamp }) => ({
            key: { token, distinctId },
            eventCount: count,
            firstTimestamp,
        })
    )
    const keysToRedirect = await overflowRedirectService.handleEventBatch('events', batches)

    return inputs.map((input, index) => {
        const eventKey = perInputKeys[index]
        if (eventKey !== null && keysToRedirect.has(eventKey)) {
            return redirect('rate_limit_exceeded', OVERFLOW_OUTPUT, preservePartitionLocality)
        }
        return ok(input)
    })
}

/**
 * Rate-limits every input regardless of cookieless mode. Keys on `event.distinct_id`.
 * Use when there is no cookieless step in the pipeline (e.g. error tracking).
 */
export interface RateLimitToOverflowStepInput {
    headers: EventHeaders
    event: PipelineEvent
}

export function createRateLimitToOverflowStep<T extends RateLimitToOverflowStepInput>(
    preservePartitionLocality: boolean,
    overflowRedirectService?: OverflowRedirectService
) {
    return async function rateLimitToOverflowStep(inputs: T[]): Promise<PipelineResult<T, OverflowOutput>[]> {
        return applyOverflowRedirect(inputs, overflowRedirectService, preservePartitionLocality, (input) => ({
            token: input.headers.token ?? '',
            distinctId: input.event.distinct_id ?? '',
        }))
    }
}

/**
 * Rate-limits only non-cookieless events using `headers.distinct_id`. Designed to run
 * before the body is parsed — it does not require `event`. Cookieless events
 * (`headers.distinct_id === COOKIELESS_SENTINEL_VALUE`) pass through untouched, to be
 * handled by `createOnlyCookielessRateLimitToOverflowStep` after the cookieless step
 * has assigned them a real hashed distinct_id.
 */
export interface SkipCookielessRateLimitToOverflowStepInput {
    headers: EventHeaders
}

export function createSkipCookielessRateLimitToOverflowStep<T extends SkipCookielessRateLimitToOverflowStepInput>(
    preservePartitionLocality: boolean,
    overflowRedirectService?: OverflowRedirectService
) {
    return async function skipCookielessRateLimitToOverflowStep(
        inputs: T[]
    ): Promise<PipelineResult<T, OverflowOutput>[]> {
        return applyOverflowRedirect(inputs, overflowRedirectService, preservePartitionLocality, (input) => {
            if (input.headers.distinct_id === COOKIELESS_SENTINEL_VALUE) {
                return null
            }
            return {
                token: input.headers.token ?? '',
                distinctId: input.headers.distinct_id ?? '',
            }
        })
    }
}

/**
 * Rate-limits only cookieless events using `event.distinct_id` (the hashed value
 * assigned by the cookieless step). Must run after `createApplyCookielessProcessingStep`,
 * not before. Pairs with `createSkipCookielessRateLimitToOverflowStep` to cover the full
 * traffic without parsing the body for non-cookieless events that are about to be redirected.
 */
export interface OnlyCookielessRateLimitToOverflowStepInput {
    headers: EventHeaders
    event: PipelineEvent
}

export function createOnlyCookielessRateLimitToOverflowStep<T extends OnlyCookielessRateLimitToOverflowStepInput>(
    preservePartitionLocality: boolean,
    overflowRedirectService?: OverflowRedirectService
) {
    return async function onlyCookielessRateLimitToOverflowStep(
        inputs: T[]
    ): Promise<PipelineResult<T, OverflowOutput>[]> {
        return applyOverflowRedirect(inputs, overflowRedirectService, preservePartitionLocality, (input) => {
            if (input.headers.distinct_id !== COOKIELESS_SENTINEL_VALUE) {
                return null
            }
            return {
                token: input.headers.token ?? '',
                distinctId: input.event.distinct_id ?? '',
            }
        })
    }
}
