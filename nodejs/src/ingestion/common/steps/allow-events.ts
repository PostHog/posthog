import { EventHeaders } from '../../../types'
import { ok } from '../../pipelines/results'
import { ProcessingStep } from '../../pipelines/steps'
import { createSendToDlqStep } from './send-to-dlq'

/**
 * DLQs any event whose header `event` name is not in the allow list.
 * Reads from the parsed Kafka headers so it can run before message-body
 * parsing — use in a consumer's pipeline to enforce that only its
 * target event type(s) flow through. Anything else is misrouted and
 * goes to the DLQ for investigation. Events with no `event` header
 * pass through (no name to match against).
 */
export function createAllowEventsStep<T extends { headers: EventHeaders }>(
    allowed: readonly string[]
): ProcessingStep<T, T> {
    const allowedSet = new Set(allowed)
    const sendToDlq = createSendToDlqStep<T>('event_not_in_allowlist')
    return function allowEventsStep(input) {
        const name = input.headers.event
        if (name === undefined || allowedSet.has(name)) {
            return Promise.resolve(ok(input))
        }
        return sendToDlq(input)
    }
}
