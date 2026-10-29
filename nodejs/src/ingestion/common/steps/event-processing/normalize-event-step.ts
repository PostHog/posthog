import { DateTime } from 'luxon'

import { normalizeEvent, normalizeOsAlias, normalizeProcessPerson, sanitizeEvent } from '~/common/utils/event'
import { parseEventTimestamp } from '~/ingestion/common/timestamps'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent, Properties } from '~/plugin-scaffold'
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
        const snapshot = input.headers.person_properties_snapshot
        const normalizedEvent = snapshot === undefined ? normalizeEvent(event) : sanitizeEvent(event)
        if (snapshot !== undefined) {
            // The snapshot already includes enrichment from the source project.
            const properties: Properties = { ...normalizedEvent.properties, $set: structuredClone(snapshot) }
            delete properties.$set_once
            delete properties.$unset
            delete normalizedEvent.$set
            delete normalizedEvent.$set_once
            normalizeOsAlias(properties)
            normalizedEvent.properties = properties
        }
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
