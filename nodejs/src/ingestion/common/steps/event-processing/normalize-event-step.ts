import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/node-common/plugin-scaffold'
import { normalizeEvent, normalizeProcessPerson } from '@posthog/node-common/utils/event'

import { parseEventTimestamp } from '~/ingestion/common/timestamps'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders } from '~/types'

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
