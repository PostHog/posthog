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

export type CreateEventStepResult<TInput = CreateEventStepInput> = TInput & {
    eventToEmit: RawKafkaEvent
}

export function createCreateEventStep<T extends CreateEventStepInput>(): ProcessingStep<T, CreateEventStepResult<T>> {
    return function createEventStep(input: T): Promise<PipelineResult<CreateEventStepResult<T>>> {
        const { person, preparedEvent, processPerson, historicalMigration, headers } = input

        const capturedAt = headers.now ?? null
        const rawEvent = createEvent(preparedEvent, person, processPerson, historicalMigration, capturedAt)

        return Promise.resolve(ok({ ...input, eventToEmit: rawEvent }, []))
    }
}
