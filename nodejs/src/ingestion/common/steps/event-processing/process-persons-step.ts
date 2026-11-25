import { DateTime } from 'luxon'

import { AsyncOutput } from '~/common/outputs'
import { PersonhogUnprocessablePersonError } from '~/common/personhog/persons'
import { logger } from '~/common/utils/logger'
import { PersonContext, PersonOutputs } from '~/ingestion/common/persons/person-context'
import { PersonEventProcessor } from '~/ingestion/common/persons/person-event-processor'
import type { MergeFoldDecision } from '~/ingestion/common/persons/person-merge-fold'
import { PersonMergeService } from '~/ingestion/common/persons/person-merge-service'
import { determineMergeMode } from '~/ingestion/common/persons/person-merge-types'
import { PersonPropertyService } from '~/ingestion/common/persons/person-property-service'
import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { PipelineResult, drop, isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { Person, Team } from '~/types'

import { EventPipelineRunnerOptions } from './event-pipeline-options'

const UNPROCESSABLE_PERSON_MESSAGE =
    "This person's stored properties cannot be read, so events for this person are dropped. " +
    'This usually means the properties are nested more than 128 levels deep, because an object such as ' +
    'a DOM element or an SDK instance was set as a person property. Delete this person to resume ' +
    'processing their events, and pass a plain value where the property is set.'

export type ProcessPersonsInput = {
    normalizedEvent: PluginEvent
    team: Team
    timestamp: DateTime
    personlessPerson?: Person
    personsStoreForBatch: PersonsStoreForBatch
    /** The merge-fold planning decision for this event; `immediate` everywhere except planned $identify runs in the grouped analytics lane. */
    mergeFold: MergeFoldDecision
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
            input.mergeFold.type === 'planned' ? input.mergeFold.plan : undefined,
            options.PERSONHOG_IDENTITY_EMITS_MERGE_WARNINGS,
            options.PERSON_MERGE_NOT_APPLIED_WAIT_MS
        )

        const processor = new PersonEventProcessor(
            context,
            new PersonPropertyService(context),
            new PersonMergeService(context)
        )
        let result: PipelineResult<Person, AsyncOutput>
        try {
            result = await processor.processEvent()
        } catch (error) {
            if (!(error instanceof PersonhogUnprocessablePersonError)) {
                throw error
            }
            logger.warn('🤔', 'stored person properties cannot be parsed; the event is dropped', {
                team_id: error.teamId,
                person_id: error.personId,
                distinct_id: normalizedEvent.distinct_id,
                event_uuid: normalizedEvent.uuid,
            })
            return drop(
                'unprocessable_person',
                [],
                [
                    {
                        type: 'person_properties_depth_violation',
                        details: {
                            distinctId: normalizedEvent.distinct_id,
                            eventUuid: normalizedEvent.uuid,
                            message: UNPROCESSABLE_PERSON_MESSAGE,
                        },
                        pipelineStep: 'person-store',
                        key: String(normalizedEvent.distinct_id),
                    },
                ]
            )
        }

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
