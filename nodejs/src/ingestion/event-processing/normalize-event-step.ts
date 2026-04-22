import { DateTime } from 'luxon'

import { PluginEvent } from '~/plugin-scaffold'

import { EventHeaders } from '../../types'
import { normalizeEvent, normalizeProcessPerson } from '../../utils/event'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
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
    return function normalizeEventStepWrapper(
        input: TInput
    ): Promise<PipelineResult<Omit<TInput, 'event'> & NormalizeEventOutput>> {
        const { event, ...restInput } = input
        const normalizedEvent = normalizeEvent(event)
        normalizeProcessPerson(normalizedEvent, input.processPerson)

        const timestamp = parseEventTimestamp(normalizedEvent)

        return Promise.resolve(
            ok({
                ...restInput,
                normalizedEvent,
                timestamp,
            })
        )
    }
}
