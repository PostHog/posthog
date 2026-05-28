import { dlq } from '../../pipelines/results'
import { ProcessingStep } from '../../pipelines/steps'

/**
 * Pipeline step that unconditionally sends its input to the DLQ with the
 * given reason. Meant to be used inside conditional branches that need
 * to reject events out of band — e.g. when a consumer sees an event
 * type that belongs in a different consumer's pipeline.
 */
export function createSendToDlqStep<T>(reason: string): ProcessingStep<T, T> {
    return function sendToDlqStep() {
        return Promise.resolve(dlq(reason))
    }
}
