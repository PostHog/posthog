import { EventHeaders, IncomingEventWithTeam } from '../../types'
import { PipelineResult, ok, redirect } from '../pipelines/results'
import { OverflowEventBatch, OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'

export interface RateLimitToOverflowStepInput {
    headers: EventHeaders
    eventWithTeam: IncomingEventWithTeam
}

export function createRateLimitToOverflowStep<T extends RateLimitToOverflowStepInput>(
    overflowTopic: string,
    preservePartitionLocality: boolean,
    overflowRedirectService?: OverflowRedirectService
) {
    return async function rateLimitToOverflowStep(inputs: T[]): Promise<PipelineResult<T>[]> {
        if (!overflowRedirectService) {
            return inputs.map((input) => ok(input))
        }

        // Count events by token:distinct_id and track first timestamp
        // NOTE: headers.token and headers.now are safe to use as they don't change during processing.
        // However, headers.distinct_id is NOT safe because cookieless processing may change the
        // distinct_id from the sentinel value - use eventWithTeam.event.distinct_id instead.
        const keyStats = new Map<string, { token: string; distinctId: string; count: number; firstTimestamp: number }>()

        for (const { headers, eventWithTeam } of inputs) {
            const token = headers.token ?? ''
            const distinctId = eventWithTeam.event.distinct_id ?? ''
            const eventKey = `${token}:${distinctId}`
            const timestamp = headers.now?.getTime() ?? Date.now()

            const existing = keyStats.get(eventKey)
            if (existing) {
                existing.count++
            } else {
                keyStats.set(eventKey, { token, distinctId, count: 1, firstTimestamp: timestamp })
            }
        }

        // Service handles all overflow logic (rate limiting + optional Redis coordination)
        const batches: OverflowEventBatch[] = Array.from(keyStats.values()).map(
            ({ token, distinctId, count, firstTimestamp }) => ({
                key: { token, distinctId },
                eventCount: count,
                firstTimestamp,
            })
        )
        const keysToRedirect = await overflowRedirectService.handleEventBatch('events', batches)

        // Build results in original order
        return inputs.map((input) => {
            const { headers, eventWithTeam } = input
            const token = headers.token ?? ''
            const distinctId = eventWithTeam.event.distinct_id ?? ''
            const eventKey = `${token}:${distinctId}`

            if (keysToRedirect.has(eventKey)) {
                return redirect('rate_limit_exceeded', overflowTopic, preservePartitionLocality)
            } else {
                return ok(input)
            }
        })
    }
}
