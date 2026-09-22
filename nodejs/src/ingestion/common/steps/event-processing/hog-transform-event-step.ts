import { Counter } from 'prom-client'

import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { isProtectedInternalEvent } from '~/common/protected-internal-events'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, Team } from '~/types'

export const hogTransformationProtectedEventSkips = new Counter({
    name: 'hog_transformation_protected_event_skips_total',
    help: 'Number of events skipped by every transformation because they are PostHog-emitted product output',
})

export interface HogTransformEventInput {
    event: PluginEvent
    team: Pick<Team, 'id'>
    headers: Pick<EventHeaders, 'event' | 'internal_producer'>
}

export interface HogTransformEventOutput {
    transformationsRun: number
}

/**
 * Creates a pipeline step that runs Hog transformations on events.
 *
 * Hog transformations are user-defined functions that can modify event properties,
 * change the event name, update distinct_id, or drop the event entirely.
 *
 * If a transformation drops the event (returns null), this step returns a `drop` result.
 */
export function createHogTransformEventStep<T extends HogTransformEventInput>(
    hogTransformer: Pick<HogTransformer, 'transformEventAndProduceMessages'> | null
): ProcessingStep<T, T & HogTransformEventOutput> {
    return async function hogTransformEventStep(input) {
        const { event } = input

        // If no transformer configured, pass through unchanged
        if (!hogTransformer) {
            return ok({ ...input, transformationsRun: 0 })
        }

        if (isProtectedInternalEvent(input.headers)) {
            hogTransformationProtectedEventSkips.inc()
            return ok({ ...input, transformationsRun: 0 })
        }

        const result = await hogTransformer.transformEventAndProduceMessages(event)

        // If transformation dropped the event, return drop result with a warning
        // so the user can see which transformation dropped it
        if (result.event === null) {
            const warning: PipelineWarning = {
                type: 'event_dropped_by_transformation',
                details: {
                    eventUuid: event.uuid,
                    event: event.event,
                    distinctId: event.distinct_id,
                    transformationId: result.droppedBy?.id,
                    transformationName: result.droppedBy?.name,
                },
                pipelineStep: 'hog-transform',
                // Debounce per transformation so each dropping transformation surfaces
                key: result.droppedBy?.id,
            }
            return drop('dropped_by_transformation', [], [warning])
        }

        return ok({
            ...input,
            event: result.event,
            transformationsRun: result.invocationResults.length,
        })
    }
}
