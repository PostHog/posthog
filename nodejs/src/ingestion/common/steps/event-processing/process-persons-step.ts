import { DateTime } from 'luxon'

import { AsyncOutput } from '~/common/outputs'
import { PersonContext, PersonOutputs } from '~/ingestion/common/persons/person-context'
import { PersonEventProcessor } from '~/ingestion/common/persons/person-event-processor'
import { PersonMergeService } from '~/ingestion/common/persons/person-merge-service'
import { determineMergeMode } from '~/ingestion/common/persons/person-merge-types'
import { PersonPropertyService } from '~/ingestion/common/persons/person-property-service'
import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { PipelineResult, isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { Person, Team } from '~/types'

import { EventPipelineRunnerOptions } from './event-pipeline-options'

export type ProcessPersonsInput = {
    normalizedEvent: PluginEvent
    team: Team
    timestamp: DateTime
    personlessPerson?: Person
    personsStoreForBatch: PersonsStoreForBatch
}

export type ProcessPersonsOutput = {
    person: Person
}

export function createProcessPersonsStep<TInput extends ProcessPersonsInput>(
    options: EventPipelineRunnerOptions,
    personOutputs: PersonOutputs
): ProcessingStep<TInput, TInput & ProcessPersonsOutput, AsyncOutput> {
    const mergeMode = determineMergeMode(
        options.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
        options.PERSON_MERGE_ASYNC_ENABLED,
        options.PERSON_MERGE_SYNC_BATCH_SIZE
    )

    return async function processPersonsStep(
        input: TInput
    ): Promise<PipelineResult<TInput & ProcessPersonsOutput, AsyncOutput>> {
        const { normalizedEvent, team, timestamp, personlessPerson, personsStoreForBatch } = input

        if (personlessPerson && !personlessPerson.force_upgrade) {
            return ok({ ...input, person: personlessPerson })
        }

        const shouldUpdateLastSeenAt = team.extra_settings?.person_last_seen_at_enabled === true

        const context = new PersonContext(
            normalizedEvent,
            team,
            String(normalizedEvent.distinct_id),
            timestamp,
            true,
            personOutputs,
            personsStoreForBatch,
            options.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
            mergeMode,
            options.PERSON_PROPERTIES_UPDATE_ALL,
            shouldUpdateLastSeenAt,
            {
                enabled: options.PERSON_MERGE_EVENTS_ENABLED,
                partitionCount: options.PERSON_MERGE_EVENTS_PARTITION_COUNT,
            }
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
