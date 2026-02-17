import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { EventHeaders, PipelineEvent, Team } from '../../types'
import { normalizeEventStep } from '../../worker/ingestion/event-pipeline/normalizeEventStep'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createNormalizeEventStep<
    TInput extends { event: PluginEvent; headers: EventHeaders; team: Team; processPerson: boolean },
>(
    timestampComparisonLoggingSampleRate: number
): ProcessingStep<TInput, TInput & { normalizedEvent: PipelineEvent; timestamp: DateTime }> {
    return async function normalizeEventStepWrapper(
        input: TInput
    ): Promise<PipelineResult<TInput & { normalizedEvent: PipelineEvent; timestamp: DateTime }>> {
        const [normalizedEvent, timestamp] = await normalizeEventStep(
            input.event,
            input.processPerson,
            input.headers,
            timestampComparisonLoggingSampleRate
        )

        return ok({
            ...input,
            normalizedEvent,
            timestamp,
        })
    }
}
