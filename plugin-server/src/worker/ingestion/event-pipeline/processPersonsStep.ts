import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { Person, Team } from '~/types'

import { PipelineResult, isOkResult, ok } from '../../../ingestion/pipelines/results'
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
): Promise<PipelineResult<[PluginEvent, Person, Promise<void>]>> {
    const context = new PersonContext(
        event,
        team,
        String(event.distinct_id),
        timestamp,
        processPerson,
        runner.hub.db.kafkaProducer,
        personStoreBatch,
        runner.hub.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
        runner.mergeMode
    )

    const processor = new PersonEventProcessor(
        context,
        new PersonPropertyService(context),
        new PersonMergeService(context)
    )
    const [result, kafkaAck] = await processor.processEvent()

    if (isOkResult(result)) {
        return ok([event, result.value, kafkaAck])
    } else {
        return result
    }
}
