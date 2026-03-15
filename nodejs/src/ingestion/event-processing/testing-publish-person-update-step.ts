import { DateTime } from 'luxon'

import { PluginEvent, Properties } from '~/plugin-scaffold'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { InternalPerson, Person, Team } from '../../types'
import { generateKafkaPersonUpdateMessage } from '../../utils/db/utils'
import { uuidFromDistinctId } from '../../worker/ingestion/person-uuid'
import { PropertyUpdates } from '../../worker/ingestion/persons/person-update'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

// Events that set updateIsIdentified = true in the original pipeline,
// triggering a person update even without property changes
const IDENTIFY_EVENTS = new Set(['$identify', '$create_alias', '$merge_dangerously'])

export type PublishPersonUpdateInput = {
    normalizedEvent: PluginEvent
    team: Team
    person?: Person
    personPropertyUpdates?: PropertyUpdates
}

export type PublishPersonUpdateOutput = {
    person: Person
}

/**
 * Approximates the Kafka person update messages from the original pipeline
 * without any DB reads or writes:
 *
 * 1. No person found → builds a fake person with $set/$set_once from the
 *    event and publishes a Kafka message (approximates person creation).
 * 2. Person found + property changes → publishes with the merged person.
 * 3. Person found + identify-type event ($identify, $create_alias,
 *    $merge_dangerously) → publishes even without property changes
 *    (approximates the is_identified update).
 * 4. Person found + no changes + not an identify event → no publish.
 */
export function createTestingPublishPersonUpdateStep<TInput extends PublishPersonUpdateInput>(
    kafkaProducer: KafkaProducerWrapper
): ProcessingStep<TInput, TInput & PublishPersonUpdateOutput> {
    return function testingPublishPersonUpdateStep(
        input: TInput
    ): Promise<PipelineResult<TInput & PublishPersonUpdateOutput>> {
        const { normalizedEvent, team, person, personPropertyUpdates } = input

        if (!person) {
            // Approximate person creation: apply $set_once then $set
            const properties: Properties = {}
            const setOnceProps: Properties = normalizedEvent.properties?.['$set_once'] || {}
            const setProps: Properties = normalizedEvent.properties?.['$set'] || {}
            Object.assign(properties, setOnceProps, setProps)

            const fakePerson: Person = {
                team_id: team.id,
                properties,
                uuid: uuidFromDistinctId(team.id, normalizedEvent.distinct_id),
                created_at: DateTime.utc(1970, 1, 1, 0, 0, 5),
            }

            const kafkaAck = kafkaProducer.queueMessages(generateKafkaPersonUpdateMessage(personToInternal(fakePerson)))
            return Promise.resolve(ok({ ...input, person: fakePerson }, [kafkaAck]))
        }

        const isIdentifyEvent = IDENTIFY_EVENTS.has(normalizedEvent.event)
        const hasChanges = personPropertyUpdates?.hasChanges || isIdentifyEvent

        if (!hasChanges) {
            return Promise.resolve(ok({ ...input, person }))
        }

        const internalPerson = personToInternal(person)
        if (isIdentifyEvent) {
            internalPerson.is_identified = true
        }

        const kafkaAck = kafkaProducer.queueMessages(generateKafkaPersonUpdateMessage(internalPerson))
        return Promise.resolve(ok({ ...input, person }, [kafkaAck]))
    }
}

function personToInternal(person: Person): InternalPerson {
    return {
        id: '0',
        team_id: person.team_id,
        properties: person.properties,
        uuid: person.uuid,
        created_at: person.created_at,
        is_user_id: null,
        is_identified: false,
        version: 0,
        last_seen_at: null,
        properties_last_updated_at: {},
        properties_last_operation: null,
    }
}
