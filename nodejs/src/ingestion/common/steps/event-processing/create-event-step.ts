import { Message } from 'node-rdkafka'

import { createEvent } from '~/ingestion/common/steps/event-processing/create-event'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders, Person, PreIngestionEvent } from '~/types'

import { EventToEmit } from './emit-event-step'

const EXPERIMENT_EXPOSURE_TEAM_ID = 2
const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'
const EXPERIMENT_EXPOSURE_EVENT = '$experiment_exposure'

function isMultivariateFeatureFlagCalledEvent(event: PreIngestionEvent): boolean {
    const response = event.properties['$feature_flag_response']

    return (
        event.teamId === EXPERIMENT_EXPOSURE_TEAM_ID &&
        event.event === FEATURE_FLAG_CALLED_EVENT &&
        typeof response === 'string' &&
        response !== '' &&
        response !== 'true' &&
        response !== 'false'
    )
}

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
    output: O
): ProcessingStep<T, CreateEventStepResult<O>> {
    return function createEventStep(input) {
        const { person, preparedEvent, processPerson, historicalMigration, headers, message } = input

        const capturedAt = headers.now ?? null
        const rawEvent = createEvent(preparedEvent, person, processPerson, historicalMigration, capturedAt)
        const eventsToEmit: EventToEmit<O>[] = [{ event: rawEvent, output }]

        if (isMultivariateFeatureFlagCalledEvent(preparedEvent)) {
            eventsToEmit.push({ event: { ...rawEvent, event: EXPERIMENT_EXPOSURE_EVENT }, output })
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
