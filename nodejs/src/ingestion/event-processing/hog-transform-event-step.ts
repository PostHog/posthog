import { PluginEvent } from '~/plugin-scaffold'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Team } from '../../types'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface HogTransformEventInput {
    event: PluginEvent
    team: Pick<Team, 'id'>
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
    hogTransformer: Pick<HogTransformerService, 'transformEventAndProduceMessages'> | null
): ProcessingStep<T, T & HogTransformEventOutput> {
    return async function hogTransformEventStep(input) {
        const { event } = input

        // If no transformer configured, pass through unchanged
        if (!hogTransformer) {
            return ok({ ...input, transformationsRun: 0 })
        }

        const result = await hogTransformer.transformEventAndProduceMessages(event)

        // If transformation dropped the event, return drop result
        if (result.event === null) {
            return drop('dropped_by_transformation')
        }

        return ok({
            ...input,
            event: result.event,
            transformationsRun: result.invocationResults.length,
        })
    }
}
