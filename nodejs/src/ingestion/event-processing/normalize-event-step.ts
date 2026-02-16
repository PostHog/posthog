import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { EventHeaders } from '../../types'
import { normalizeEventStep } from '../../worker/ingestion/event-pipeline/normalizeEventStep'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

type NormalizeEventInput = {
    event: PluginEvent
    headers: EventHeaders
    processPerson: boolean
}

type NormalizeEventOutput = {
    normalizedEvent: PluginEvent
    timestamp: DateTime
}

export function createNormalizeEventStep<TInput extends NormalizeEventInput>(): ProcessingStep<
    TInput,
    TInput & NormalizeEventOutput
> {
    return async function normalizeEventStepWrapper(
        input: TInput
    ): Promise<PipelineResult<TInput & NormalizeEventOutput>> {
        const [normalizedEvent, timestamp] = await normalizeEventStep(input.event, input.processPerson, input.headers)

        return ok({
            ...input,
            normalizedEvent,
            timestamp,
        })
    }
}
