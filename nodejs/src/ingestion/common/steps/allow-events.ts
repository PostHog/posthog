import { IncomingEvent } from '../../../types'
import { ok } from '../../pipelines/results'
import { ProcessingStep } from '../../pipelines/steps'
import { createSendToDlqStep } from './send-to-dlq'

/**
 * DLQs any event whose name is not in the allow list. Use this in a
 * consumer's pipeline to enforce that only its target event type(s)
 * flow through — anything else is misrouted and goes to the DLQ for
 * investigation.
 */
export function createAllowEventsStep<T extends { event: IncomingEvent }>(
    allowed: readonly string[]
): ProcessingStep<T, T> {
    const allowedSet = new Set(allowed)
    const sendToDlq = createSendToDlqStep<T>('event_not_in_allowlist')
    return function allowEventsStep(input) {
        if (allowedSet.has(input.event.event.event)) {
            return Promise.resolve(ok(input))
        }
        return sendToDlq(input)
    }
}
