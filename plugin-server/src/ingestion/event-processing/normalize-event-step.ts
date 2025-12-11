import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { EventHeaders, Hub, PipelineEvent, Team } from '../../types'
import { normalizeEventStep } from '../../worker/ingestion/event-pipeline/normalizeEventStep'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createNormalizeEventStep<
    TInput extends { event: PipelineEvent; headers: EventHeaders; team: Team; processPerson: boolean },
>(
    hub: Pick<Hub, 'TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE'>
): ProcessingStep<TInput, Omit<TInput, 'event'> & { normalizedEvent: PipelineEvent; timestamp: DateTime }> {
    return async function normalizeEventStepWrapper(
        input: TInput
    ): Promise<PipelineResult<Omit<TInput, 'event'> & { normalizedEvent: PipelineEvent; timestamp: DateTime }>> {
        const { event: event, ...restInput } = input

        const pluginEvent: PluginEvent = {
            ...event,
            team_id: input.team.id,
        }

        const [normalizedEvent, timestamp] = await normalizeEventStep(
            pluginEvent,
            input.processPerson,
            input.headers,
            hub.TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE
        )

        return ok({
            ...restInput,
            normalizedEvent,
            timestamp,
        })
    }
}
