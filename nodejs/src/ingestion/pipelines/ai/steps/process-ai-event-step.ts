import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { AI_EVENT_TYPES } from '~/ingestion/common/ai-event-types'
import { dlq, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { processAiEvent } from '~/ingestion/pipelines/ai/process-ai-event'
import { PluginEvent } from '~/plugin-scaffold'

type ProcessAiEventInput = {
    normalizedEvent: PluginEvent
}

export function createProcessAiEventStep<TInput extends ProcessAiEventInput>(): ProcessingStep<TInput, TInput> {
    return function processAiEventStep(input) {
        if (!AI_EVENT_TYPES.has(input.normalizedEvent.event)) {
            return Promise.resolve(
                dlq(
                    'non-AI event routed to AI subpipeline',
                    new Error(`unexpected event type: ${input.normalizedEvent.event}`)
                )
            )
        }

        try {
            // processAiEvent only adds/modifies properties — it doesn't change
            // event name, distinct_id, or timestamps, so no re-normalization needed.
            const enrichedEvent = processAiEvent(input.normalizedEvent)
            return Promise.resolve(ok({ ...input, normalizedEvent: enrichedEvent }))
        } catch (error) {
            // NOTE: processAiEvent mutates the event in place, so on error the
            // event may be partially enriched. This is acceptable — downstream
            // consumers should not rely on AI fields being complete.
            captureException(error)
            logger.error('Failed to process AI event, passing through with partial enrichment', {
                event: input.normalizedEvent.event,
                error,
            })
            return Promise.resolve(ok(input))
        }
    }
}
