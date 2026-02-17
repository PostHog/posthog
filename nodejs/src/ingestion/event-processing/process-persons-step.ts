import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { Person, Team } from '../../types'
import { processPersonsStep } from '../../worker/ingestion/event-pipeline/processPersonsStep'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { determineMergeMode } from '../../worker/ingestion/persons/person-merge-types'
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

    return async function processPersonsStepWrapper(
        input: TInput
    ): Promise<PipelineResult<TInput & ProcessPersonsOutput>> {
        const { normalizedEvent, team, timestamp, personlessPerson } = input

        let person: Person
        let postPersonEvent = normalizedEvent
        const sideEffects: Promise<unknown>[] = []

        let shouldProcessPerson = !personlessPerson
        let forceUpgrade = false

        if (personlessPerson) {
            person = personlessPerson
            forceUpgrade = !!person.force_upgrade
            shouldProcessPerson = forceUpgrade
        }

        if (shouldProcessPerson) {
            const result = await processPersonsStep(
                kafkaProducer,
                mergeMode,
                options.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
                options.PERSON_PROPERTIES_UPDATE_ALL,
                normalizedEvent,
                team,
                timestamp,
                true,
                personsStore
            )

            if (!isOkResult(result)) {
                return result
            }

            const [processedEvent, processedPerson, ack] = result.value
            postPersonEvent = processedEvent
            person = processedPerson
            sideEffects.push(ack)

            if (forceUpgrade) {
                person.force_upgrade = true
            }
        }

        return ok(
            {
                ...input,
                normalizedEvent: postPersonEvent,
                person: person!,
            },
            sideEffects
        )
    }
}
