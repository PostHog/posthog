import { Message } from 'node-rdkafka'

import { EventHeaders, Person, PreIngestionEvent } from '../../types'
import { createEvent } from '../../worker/ingestion/create-event'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { EventToEmit } from './emit-event-step'

export interface CreateEventStepInput {
    person: Person
    preparedEvent: PreIngestionEvent
    processPerson: boolean
    historicalMigration: boolean
    headers: EventHeaders
    message: Message
}

export interface CreateEventStepResult<O extends string> {
    eventsToEmit: EventToEmit<O>[]
    teamId: number
    headers: EventHeaders
    message: Message
}

export function createCreateEventStep<O extends string, T extends CreateEventStepInput>(
    output: O
): ProcessingStep<T, CreateEventStepResult<O>> {
    return function createEventStep(input) {
        const { person, preparedEvent, processPerson, historicalMigration, headers, message } = input

        const capturedAt = headers.now ?? null
        const rawEvent = createEvent(preparedEvent, person, processPerson, historicalMigration, capturedAt)
        const result: CreateEventStepResult<O> = {
            eventsToEmit: [{ event: rawEvent, output }],
            teamId: preparedEvent.teamId,
            headers,
            message,
        }

        return Promise.resolve(ok(result, []))
    }
}
