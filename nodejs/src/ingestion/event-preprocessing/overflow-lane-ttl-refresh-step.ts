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
    return async function overflowLaneTTLRefreshStep(inputs: T[]): Promise<PipelineResult<T>[]> {
        if (inputs.length === 0 || !overflowRedirectService) {
            return inputs.map((input) => ok(input))
        }

        // Group events by token:distinct_id for batch TTL refresh
        const keyStats = new Map<string, { token: string; distinctId: string; firstTimestamp: number }>()

        for (const { headers, eventWithTeam } of inputs) {
            const token = headers.token ?? ''
            const distinctId = eventWithTeam.event.distinct_id ?? ''
            const eventKey = `${token}:${distinctId}`
            const timestamp = headers.now?.getTime() ?? Date.now()

            if (!keyStats.has(eventKey)) {
                keyStats.set(eventKey, { token, distinctId, firstTimestamp: timestamp })
            }
        }

        // Build batches and refresh TTLs
        const batches: OverflowEventBatch[] = Array.from(keyStats.values()).map(
            ({ token, distinctId, firstTimestamp }) => ({
                key: { token, distinctId },
                eventCount: 1, // Count doesn't matter for TTL refresh
                firstTimestamp,
            })
        )

        await overflowRedirectService.handleEventBatch('events', batches)

        // All events continue processing in overflow lane
        return inputs.map((input) => ok(input))
    }
}
