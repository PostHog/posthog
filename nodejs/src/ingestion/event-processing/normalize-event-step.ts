import { DateTime } from 'luxon'

import { PluginEvent } from '~/plugin-scaffold'

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
    Omit<TInput, 'event'> & NormalizeEventOutput
> {
    return async function normalizeEventStepWrapper(
        input: TInput
    ): Promise<PipelineResult<Omit<TInput, 'event'> & NormalizeEventOutput>> {
        const { event, ...restInput } = input
        const [normalizedEvent, timestamp] = await normalizeEventStep(input.event, input.processPerson)

        return ok({
            ...restInput,
            normalizedEvent,
            timestamp,
        })
    }
}
