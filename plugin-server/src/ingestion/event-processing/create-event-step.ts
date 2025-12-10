import { EventHeaders, Person, PreIngestionEvent, RawKafkaEvent } from '../../types'
import { createEvent } from '../../worker/ingestion/create-event'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface CreateEventStepInput {
    person: Person
    preparedEvent: PreIngestionEvent
    processPerson: boolean
    historicalMigration: boolean
    inputHeaders: EventHeaders
}

export interface CreateEventStepResult {
    eventToEmit?: RawKafkaEvent
}

export function createCreateEventStep<T extends CreateEventStepInput>(): ProcessingStep<T, CreateEventStepResult> {
    return function createEventStep(input: T): Promise<PipelineResult<CreateEventStepResult>> {
        const { person, preparedEvent, processPerson, historicalMigration, inputHeaders } = input

        const capturedAt = inputHeaders.now ?? null
        const rawEvent = createEvent(preparedEvent, person, processPerson, historicalMigration, capturedAt)
        const result = {
            eventToEmit: rawEvent,
        }

        return Promise.resolve(ok(result, []))
    }
}
