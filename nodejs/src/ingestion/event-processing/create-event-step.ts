import { Message } from 'node-rdkafka'

import { EAVEventProperty, EventHeaders, Person, PreIngestionEvent, RawKafkaEvent, Team } from '../../types'
import { MaterializedColumnSlotManager } from '../../utils/materialized-column-slot-manager'
import { createEvent } from '../../worker/ingestion/create-event'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface CreateEventStepInput {
    person: Person
    preparedEvent: PreIngestionEvent
    processPerson: boolean
    historicalMigration: boolean
    team: Team
    inputHeaders: EventHeaders
    inputMessage: Message
}

export interface CreateEventStepResult {
    eventToEmit: RawKafkaEvent
    eavPropertiesToEmit: EAVEventProperty[]
    inputHeaders: EventHeaders
    inputMessage: Message
}

export interface CreateEventStepConfig {
    materializedColumnSlotManager: MaterializedColumnSlotManager
}

export function createCreateEventStep<T extends CreateEventStepInput>(
    config: CreateEventStepConfig
): ProcessingStep<T, CreateEventStepResult> {
    const { materializedColumnSlotManager } = config

    return async function createEventStep(input: T): Promise<PipelineResult<CreateEventStepResult>> {
        const { person, preparedEvent, processPerson, historicalMigration, team, inputHeaders, inputMessage } = input

        const capturedAt = inputHeaders.now ?? null
        const materializedColumnSlots = await materializedColumnSlotManager.getSlots(team.id)

        const { event: rawEvent, eavProperties } = createEvent(
            preparedEvent,
            person,
            processPerson,
            historicalMigration,
            capturedAt,
            materializedColumnSlots
        )
        const result: CreateEventStepResult = {
            eventToEmit: rawEvent,
            eavPropertiesToEmit: eavProperties,
            inputHeaders,
            inputMessage,
        }

        return Promise.resolve(ok(result, []))
    }
}
