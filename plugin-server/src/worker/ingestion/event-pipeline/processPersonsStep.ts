import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Person, Team } from '~/src/types'

import { PersonState } from '../person-state'
import { PersonsStoreForDistinctIdBatch } from '../persons/persons-store-for-distinct-id-batch'
import { EventPipelineRunner } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    team: Team,
    timestamp: DateTime,
    processPerson: boolean,
    distinctIdBatchStore: PersonsStoreForDistinctIdBatch
): Promise<[PluginEvent, Person, Promise<void>]> {
    const [person, kafkaAck] = await new PersonState(
        event,
        team,
        String(event.distinct_id),
        timestamp,
        processPerson,
        runner.hub.db.kafkaProducer,
        distinctIdBatchStore,
        runner.hub.PERSON_JSONB_SIZE_ESTIMATE_ENABLE
    ).update()

    return [event, person, kafkaAck]
}
