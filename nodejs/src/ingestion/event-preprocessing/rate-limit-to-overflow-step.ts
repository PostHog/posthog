import { EventHeaders, IncomingEventWithTeam } from '../../types'
import { PipelineResult, ok, redirect } from '../pipelines/results'
import { MemoryRateLimiter } from '../utils/overflow-detector'

export interface RateLimitToOverflowStepInput {
    headers: EventHeaders
    eventWithTeam: IncomingEventWithTeam
}

export function createRateLimitToOverflowStep<T extends RateLimitToOverflowStepInput>(
    overflowRateLimiter: MemoryRateLimiter,
    overflowEnabled: boolean,
    overflowTopic: string,
    preservePartitionLocality: boolean
) {
    return async function rateLimitToOverflowStep(inputs: T[]): Promise<PipelineResult<T>[]> {
        if (!overflowEnabled) {
            return Promise.resolve(inputs.map((input) => ok(input)))
        }

        // Count events by token:distinct_id and track first timestamp
        // NOTE: headers.token and headers.now are safe to use as they don't change during processing.
        // However, headers.distinct_id is NOT safe because cookieless processing may change the
        // distinct_id from the sentinel value - use eventWithTeam.event.distinct_id instead.
        const keyStats = new Map<string, { count: number; firstTimestamp: number }>()

        for (const { headers, eventWithTeam } of inputs) {
            const token = headers.token ?? ''
            const distinctId = eventWithTeam.event.distinct_id ?? ''
            const eventKey = `${token}:${distinctId}`
            const timestamp = headers.now?.getTime() ?? Date.now()

            const existing = keyStats.get(eventKey)
            if (existing) {
                existing.count++
            } else {
                keyStats.set(eventKey, { count: 1, firstTimestamp: timestamp })
            }
        }

        // Check rate limiter for each key
        const shouldRedirectKey = new Map<string, boolean>()

        for (const [eventKey, stats] of keyStats) {
            const isBelowRateLimit = overflowRateLimiter.consume(eventKey, stats.count, stats.firstTimestamp)
            shouldRedirectKey.set(eventKey, !isBelowRateLimit)
        }

        // Build results in original order
        return inputs.map((input) => {
            const { headers, eventWithTeam } = input
            const token = headers.token ?? ''
            const distinctId = eventWithTeam.event.distinct_id ?? ''
            const eventKey = `${token}:${distinctId}`

            if (shouldRedirectKey.get(eventKey)) {
                return redirect('rate_limit_exceeded', overflowTopic, preservePartitionLocality)
            } else {
                return ok(input)
            }
        })
    }
}
