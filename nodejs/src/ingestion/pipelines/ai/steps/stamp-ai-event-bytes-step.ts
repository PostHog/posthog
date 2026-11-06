import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'

const AI_EVENT_BYTES_PROPERTY = '$ai_event_bytes'

type StampAiEventBytesInput = {
    normalizedEvent: PluginEvent
    eventBytes: number
}

// Billing reads this property, so it must run after the Hog transformation, the last step that can write any key.
export function createStampAiEventBytesStep<TInput extends StampAiEventBytesInput>(): ProcessingStep<TInput, TInput> {
    return function stampAiEventBytesStep(input) {
        const { normalizedEvent, eventBytes } = input
        return Promise.resolve(
            ok({
                ...input,
                normalizedEvent: {
                    ...normalizedEvent,
                    properties: { ...normalizedEvent.properties, [AI_EVENT_BYTES_PROPERTY]: eventBytes },
                },
            })
        )
    }
}
