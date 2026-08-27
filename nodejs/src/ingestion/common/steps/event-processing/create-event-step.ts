import { Message } from 'node-rdkafka'
import { parse as parseUuid, v5 as uuidv5 } from 'uuid'

import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { parseTeamsList } from '~/common/utils/env-utils'
import { createEvent } from '~/ingestion/common/steps/event-processing/create-event'
import { EventUsageRecord } from '~/ingestion/common/steps/usage-records-steps'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders, Person, PreIngestionEvent } from '~/types'

import { EventToEmit } from './emit-event-step'

const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'
const EXPERIMENT_EXPOSURE_EVENT = '$experiment_exposure'

// UUIDv5 namespace (a randomly generated UUIDv4) for deriving a duplicated exposure
// event's uuid from its source event's uuid.
const EXPERIMENT_EXPOSURE_UUIDV5_NAMESPACE = parseUuid('1b7c9119-5953-4668-97b7-ab0ef8a6bb48')

// Flag definitions aren't available in ingestion, so multivariate is inferred from the
// response shape; a variant literally keyed "true" or "false" is indistinguishable from
// a boolean flag response and knowingly skipped.
function isMultivariateFeatureFlagCalledEvent(event: PreIngestionEvent): boolean {
    const response = event.properties['$feature_flag_response']

    return (
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
    eventUsageRecord?: EventUsageRecord
    eventUsageBatch?: UsageRecordBatch
}

export interface CreateEventStepResult<O extends string> {
    eventsToEmit: EventToEmit<O>[]
    teamId: number
    headers: EventHeaders
    message: Message
    eventUsageRecord?: EventUsageRecord
    eventUsageBatch?: UsageRecordBatch
}

export function createCreateEventStep<O extends string, T extends CreateEventStepInput>(
    output: O,
    experimentExposureDuplicationTeams: string = ''
): ProcessingStep<T, CreateEventStepResult<O>> {
    const exposureDuplicationTeams = parseTeamsList(experimentExposureDuplicationTeams)

    return function createEventStep(input) {
        const {
            person,
            preparedEvent,
            processPerson,
            historicalMigration,
            headers,
            message,
            eventUsageRecord,
            eventUsageBatch,
        } = input

        const capturedAt = headers.now ?? null
        const rawEvent = createEvent(preparedEvent, person, processPerson, historicalMigration, capturedAt)
        const eventsToEmit: EventToEmit<O>[] = [{ event: rawEvent, output }]

        // Duplicated exposures build up $experiment_exposure data for allowlisted teams during
        // the migration away from $feature_flag_called-based experiment exposures. The duplicate
        // gets its own uuid because event uuids are assumed unique by lookups and API endpoints,
        // derived deterministically from the source event's uuid so that a Kafka redelivery
        // reproduces the same row, which the events table's ReplacingMergeTree can collapse.
        if (
            (exposureDuplicationTeams === '*' || exposureDuplicationTeams.includes(preparedEvent.teamId)) &&
            isMultivariateFeatureFlagCalledEvent(preparedEvent)
        ) {
            eventsToEmit.push({
                event: {
                    ...rawEvent,
                    event: EXPERIMENT_EXPOSURE_EVENT,
                    uuid: uuidv5(rawEvent.uuid, EXPERIMENT_EXPOSURE_UUIDV5_NAMESPACE),
                },
                output,
            })
        }

        const result: CreateEventStepResult<O> = {
            eventsToEmit,
            teamId: preparedEvent.teamId,
            headers,
            message,
            eventUsageRecord,
            eventUsageBatch,
        }

        return Promise.resolve(ok(result, []))
    }
}
