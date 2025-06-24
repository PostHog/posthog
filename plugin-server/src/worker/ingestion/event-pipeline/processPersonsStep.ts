import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Person, Team } from '~/types'

import { PersonContext } from '../persons/person-context'
import { PersonEventProcessor } from '../persons/person-event-processor'
import { PersonMergeService } from '../persons/person-merge-service'
import { PersonPropertyService } from '../persons/person-property-service'
import { PersonsStoreForBatch } from '../persons/persons-store-for-batch'
import { EventPipelineRunner } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    team: Team,
    timestamp: DateTime,
    processPerson: boolean,
    personStoreBatch: PersonsStoreForBatch
): Promise<[PluginEvent, Person, Promise<void>]> {
    const context = new PersonContext(
        event,
        team,
        String(event.distinct_id),
        timestamp,
        processPerson,
        runner.hub.db.kafkaProducer,
        personStoreBatch,
        runner.hub.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
        runner.hub.PERSON_PROPERTY_JSONB_UPDATE_OPTIMIZATION
    )

    const processor = new PersonEventProcessor(
        context,
        new PersonPropertyService(context),
        new PersonMergeService(context)
    )
    const [person, kafkaAck] = await processor.processEvent()

    return [event, person, kafkaAck]
}
