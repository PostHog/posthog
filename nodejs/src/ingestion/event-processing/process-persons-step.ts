import { DateTime } from 'luxon'

import { PluginEvent } from '~/plugin-scaffold'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { Person, Team } from '../../types'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { PersonContext } from '../../worker/ingestion/persons/person-context'
import { PersonEventProcessor } from '../../worker/ingestion/persons/person-event-processor'
import { PersonMergeService } from '../../worker/ingestion/persons/person-merge-service'
import { determineMergeMode } from '../../worker/ingestion/persons/person-merge-types'
import { PersonPropertyService } from '../../worker/ingestion/persons/person-property-service'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResult, isOkResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export type ProcessPersonsInput = {
    normalizedEvent: PluginEvent
    team: Team
    timestamp: DateTime
    personlessPerson?: Person
}

export type ProcessPersonsOutput = {
    person: Person
}

export function createProcessPersonsStep<TInput extends ProcessPersonsInput>(
    options: EventPipelineRunnerOptions,
    kafkaProducer: KafkaProducerWrapper,
    personsStore: PersonsStore
): ProcessingStep<TInput, TInput & ProcessPersonsOutput> {
    const mergeMode = determineMergeMode(
        options.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
        options.PERSON_MERGE_ASYNC_ENABLED,
        options.PERSON_MERGE_ASYNC_TOPIC,
        options.PERSON_MERGE_SYNC_BATCH_SIZE
    )

    return async function processPersonsStep(input: TInput): Promise<PipelineResult<TInput & ProcessPersonsOutput>> {
        const { normalizedEvent, team, timestamp, personlessPerson } = input

        if (personlessPerson && !personlessPerson.force_upgrade) {
            return ok({ ...input, person: personlessPerson })
        }

        const context = new PersonContext(
            normalizedEvent,
            team,
            String(normalizedEvent.distinct_id),
            timestamp,
            true,
            kafkaProducer,
            personsStore,
            options.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
            mergeMode,
            options.PERSON_PROPERTIES_UPDATE_ALL
        )

        const processor = new PersonEventProcessor(
            context,
            new PersonPropertyService(context),
            new PersonMergeService(context)
        )
        const result = await processor.processEvent()

        if (!isOkResult(result)) {
            return result
        }

        const person = result.value
        if (personlessPerson?.force_upgrade) {
            person.force_upgrade = true
        }

        return ok({ ...input, person }, result.sideEffects)
    }
}
