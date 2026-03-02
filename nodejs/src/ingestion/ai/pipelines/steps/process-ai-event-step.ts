import { PluginEvent } from '~/plugin-scaffold'

import { logger } from '../../../../utils/logger'
import { captureException } from '../../../../utils/posthog'
import { dlq, ok } from '../../../pipelines/results'
import { ProcessingStep } from '../../../pipelines/steps'
import { AI_EVENT_TYPES, processAiEvent } from '../../process-ai-event'

type ProcessAiEventInput = {
    normalizedEvent: PluginEvent
}

export function createProcessAiEventStep<TInput extends ProcessAiEventInput>(): ProcessingStep<TInput, TInput> {
    return function processAiEventStep(input: TInput) {
        if (!AI_EVENT_TYPES.has(input.normalizedEvent.event)) {
            return Promise.resolve(dlq('non-AI event routed to AI subpipeline', input.normalizedEvent.event))
        }

        try {
            // processAiEvent only adds/modifies properties — it doesn't change
            // event name, distinct_id, or timestamps, so no re-normalization needed.
            const enrichedEvent = processAiEvent(input.normalizedEvent)
            return Promise.resolve(ok({ ...input, normalizedEvent: enrichedEvent }))
        } catch (error) {
            captureException(error)
            logger.error('Failed to process AI event, passing through unchanged', {
                event: input.normalizedEvent.event,
                error,
            })
            return Promise.resolve(ok(input))
        }
    }
}
