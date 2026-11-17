import { AI_EVENT_BYTES_PROPERTY } from '~/ingestion/common/ai-event-types'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'

export interface StripAiEventBytesStepInput {
    normalizedEvent: PluginEvent
}

// Only the AI pipeline measures the size, so any value reaching another pipeline came from the
// client or a Hog transformation. Billing sums this property over `events`, so it must not survive.
export function createStripAiEventBytesStep<T extends StripAiEventBytesStepInput>(): ProcessingStep<T, T> {
    return function stripAiEventBytesStep(input) {
        delete input.normalizedEvent.properties?.[AI_EVENT_BYTES_PROPERTY]
        return Promise.resolve(ok(input))
    }
}
