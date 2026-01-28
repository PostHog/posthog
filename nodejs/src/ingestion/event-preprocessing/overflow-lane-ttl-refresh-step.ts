import { EventHeaders, IncomingEventWithTeam } from '../../types'
import { PipelineResult, ok } from '../pipelines/results'
import { OverflowEventBatch, OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'

export interface OverflowLaneTTLRefreshStepInput {
    headers: EventHeaders
    eventWithTeam: IncomingEventWithTeam
}

/**
 * Creates a step that refreshes TTL for overflow lane events.
 * Used in the overflow lane to keep Redis flags alive while events are being processed.
 * Once events stop coming, the flags expire and future events return to the main lane.
 *
 * If no service is provided, this step is a no-op (passthrough).
 */
export function createOverflowLaneTTLRefreshStep<T extends OverflowLaneTTLRefreshStepInput>(
    overflowRedirectService?: OverflowRedirectService
) {
    return function overflowLaneTTLRefreshStep(inputs: T[]): Promise<PipelineResult<T>[]> {
        if (inputs.length === 0 || !overflowRedirectService) {
            return Promise.resolve(inputs.map((input) => ok(input)))
        }

        // Group events by token:distinct_id for batch TTL refresh
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

        const batches: OverflowEventBatch[] = Array.from(keyStats.values()).map(
            ({ token, distinctId, count, firstTimestamp }) => ({
                key: { token, distinctId },
                eventCount: count,
                firstTimestamp,
            })
        )

        // TTL refresh doesn't affect routing, so attach it as a pipeline side effect
        // instead of blocking the pipeline on a Redis write.
        const refreshPromise = overflowRedirectService.handleEventBatch('events', batches)

        return Promise.resolve(inputs.map((input) => ok(input, [refreshPromise])))
    }
}
