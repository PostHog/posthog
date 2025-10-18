import { DateTime } from 'luxon'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventHeaders, Hub, PipelineEvent, Team } from '../../types'
import { EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { EventPipelineResult } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResult } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createEventPipelineRunnerHeatmapStep<
    TInput extends {
        normalizedEvent: PipelineEvent
        timestamp: DateTime
        team: Team
        headers: EventHeaders
        groupStoreForBatch: GroupStoreForBatch
    },
>(hub: Hub, hogTransformer: HogTransformerService, personsStore: PersonsStore): ProcessingStep<TInput, EventPipelineResult> {
    return async function eventPipelineRunnerHeatmapStep(input: TInput): Promise<PipelineResult<EventPipelineResult>> {
        const { normalizedEvent, timestamp, team, headers, groupStoreForBatch } = input

        const runner = new EventPipelineRunner(
            hub,
            normalizedEvent,
            hogTransformer,
            personsStore,
            groupStoreForBatch,
            headers
        )
        const result = await runner.runHeatmapPipeline(normalizedEvent, timestamp, team)
        return result
    }
}
