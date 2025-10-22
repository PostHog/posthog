import { DateTime } from 'luxon'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventHeaders, Hub, PipelineEvent, RawKafkaEvent, Team } from '../../types'
import { EventPipelineHeatmapResult, EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResult } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface EventPipelineRunnerHeatmapStepInput {
    normalizedEvent: PipelineEvent
    timestamp: DateTime
    team: Team
    headers: EventHeaders
    groupStoreForBatch: GroupStoreForBatch
}

export interface EventPipelineRunnerHeatmapStepResult {
    eventToEmit?: RawKafkaEvent
}

export function createEventPipelineRunnerHeatmapStep<TInput extends EventPipelineRunnerHeatmapStepInput>(
    hub: Hub,
    hogTransformer: HogTransformerService,
    personsStore: PersonsStore
): ProcessingStep<TInput, EventPipelineHeatmapResult> {
    return async function eventPipelineRunnerHeatmapStep(
        input: TInput
    ): Promise<PipelineResult<EventPipelineHeatmapResult>> {
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
