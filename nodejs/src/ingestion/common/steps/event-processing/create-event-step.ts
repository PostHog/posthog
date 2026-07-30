import { Message } from 'node-rdkafka'

import { applyExperimentExposure } from '~/ingestion/common/experiment-exposure/apply-experiment-exposure'
import { ExperimentExposureService } from '~/ingestion/common/experiment-exposure/experiment-exposure-service'
import { createEvent } from '~/ingestion/common/steps/event-processing/create-event'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders, Person, PreIngestionEvent } from '~/types'

import { EventToEmit } from './emit-event-step'

export interface CreateEventStepInput {
    person?: Person
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
    output: O,
    experimentExposureService?: ExperimentExposureService
): ProcessingStep<T, CreateEventStepResult<O>> {
    return function createEventStep(input) {
        const { person, preparedEvent, processPerson, historicalMigration, headers, message } = input

        const capturedAt = headers.now ?? null
        const rawEvent = createEvent(preparedEvent, person, processPerson, historicalMigration, capturedAt)
        const eventsToEmit: EventToEmit<O>[] = [{ event: rawEvent, output }]

        const exposure = applyExperimentExposure(rawEvent, experimentExposureService)
        if (exposure) {
            eventsToEmit.push({ event: exposure, output })
        }

        const result: CreateEventStepResult<O> = {
            eventsToEmit,
            teamId: preparedEvent.teamId,
            headers,
            message,
        }

        return Promise.resolve(ok(result, []))
    }
}
