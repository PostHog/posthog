import { IncomingEvent } from '../../../types'
import { ok } from '../../pipelines/results'
import { ProcessingStep } from '../../pipelines/steps'
import { createSendToDlqStep } from './send-to-dlq'

/**
 * DLQs any event whose name is in the deny list. Use this in a
 * consumer's pipeline to block specific event types that belong in a
 * different consumer — anything matching the list is misrouted and
 * goes to the DLQ for investigation.
 */
export function createDenyEventsStep<T extends { event: IncomingEvent }>(
    denied: readonly string[]
): ProcessingStep<T, T> {
    const deniedSet = new Set(denied)
    const sendToDlq = createSendToDlqStep<T>('event_in_denylist')
    return function denyEventsStep(input) {
        if (deniedSet.has(input.event.event.event)) {
            return sendToDlq(input)
        }
        return Promise.resolve(ok(input))
    }
}
