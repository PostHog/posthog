import { PluginEvent } from '@posthog/plugin-scaffold'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { PipelineEvent, Team } from '../../types'
import { PipelineResult, drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface HogTransformEventInput {
    event: PipelineEvent
    team: Pick<Team, 'id'>
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
    hogTransformer: HogTransformerService | null
): ProcessingStep<T, T> {
    return async function hogTransformEventStep(input: T): Promise<PipelineResult<T>> {
        const { event, team } = input

        // If no transformer configured, pass through unchanged
        if (!hogTransformer) {
            return ok(input)
        }

        // Convert PipelineEvent to PluginEvent for transformation
        const pluginEvent: PluginEvent = {
            ...event,
            team_id: team.id,
        }

        const result = await hogTransformer.transformEventAndProduceMessages(pluginEvent)

        // If transformation dropped the event, return drop result
        if (result.event === null) {
            return drop('dropped_by_transformation')
        }

        // Convert back to PipelineEvent (preserve team_id as optional)
        const transformedEvent: PipelineEvent = {
            ...result.event,
            team_id: result.event.team_id,
        }

        return ok({
            ...input,
            event: transformedEvent,
        })
    }
}
