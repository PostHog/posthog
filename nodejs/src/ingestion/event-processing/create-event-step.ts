import { Message } from 'node-rdkafka'

import { EventHeaders, Person, PreIngestionEvent, RawKafkaEvent } from '../../types'
import { createEvent } from '../../worker/ingestion/create-event'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface CreateEventStepInput {
    person: Person
    preparedEvent: PreIngestionEvent
    processPerson: boolean
    historicalMigration: boolean
    headers: EventHeaders
    message: Message
}

export interface CreateEventStepResult {
    eventToEmit: RawKafkaEvent
    headers: EventHeaders
    message: Message
}

export function createCreateEventStep<T extends CreateEventStepInput>(): ProcessingStep<T, CreateEventStepResult> {
    return function createEventStep(input: T): Promise<PipelineResult<CreateEventStepResult>> {
        const { person, preparedEvent, processPerson, historicalMigration, headers, message } = input

        const capturedAt = headers.now ?? null
        const rawEvent = createEvent(preparedEvent, person, processPerson, historicalMigration, capturedAt)
        const result: CreateEventStepResult = {
            eventToEmit: rawEvent,
            headers,
            message,
        }

        return Promise.resolve(ok(result, []))
    }
}
