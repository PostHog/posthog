import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

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
    eventWithPerson: PluginEvent
    person: Person
}

export function createProcessPersonsStep<TInput extends ProcessPersonsInput>(
    options: EventPipelineRunnerOptions,
    kafkaProducer: KafkaProducerWrapper,
    personsStore: PersonsStore
): ProcessingStep<TInput, Omit<TInput, 'normalizedEvent'> & ProcessPersonsOutput> {
    const mergeMode = determineMergeMode(
        options.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
        options.PERSON_MERGE_ASYNC_ENABLED,
        options.PERSON_MERGE_ASYNC_TOPIC,
        options.PERSON_MERGE_SYNC_BATCH_SIZE
    )

    return async function processPersonsStep(
        input: TInput
    ): Promise<PipelineResult<Omit<TInput, 'normalizedEvent'> & ProcessPersonsOutput>> {
        const { normalizedEvent, team, timestamp, personlessPerson } = input

        let person: Person
        const sideEffects: Promise<unknown>[] = []

        let shouldProcessPerson = !personlessPerson
        let forceUpgrade = false

        if (personlessPerson) {
            person = personlessPerson
            forceUpgrade = !!person.force_upgrade
            shouldProcessPerson = forceUpgrade
        }

        if (shouldProcessPerson) {
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
            const [result, kafkaAck] = await processor.processEvent()

            if (!isOkResult(result)) {
                return result
            }

            person = result.value
            sideEffects.push(kafkaAck)

            if (forceUpgrade) {
                person.force_upgrade = true
            }
        }

        const { normalizedEvent: _, ...rest } = input
        return ok(
            {
                ...rest,
                eventWithPerson: normalizedEvent,
                person: person!,
            } as Omit<TInput, 'normalizedEvent'> & ProcessPersonsOutput,
            sideEffects
        )
    }
}
