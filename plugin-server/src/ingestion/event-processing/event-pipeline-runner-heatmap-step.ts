import { DateTime } from 'luxon'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventHeaders, Hub, PipelineEvent, RawKafkaEvent, Team } from '../../types'
import { EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStoreForBatch } from '../../worker/ingestion/persons/persons-store-for-batch'
import { PipelineResult } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface EventPipelineRunnerHeatmapStepInput {
    normalizedEvent: PipelineEvent
    timestamp: DateTime
    team: Team
    headers: EventHeaders
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
}

export interface EventPipelineRunnerHeatmapStepResult {
    eventToEmit?: RawKafkaEvent
}

export function createEventPipelineRunnerHeatmapStep<TInput extends EventPipelineRunnerHeatmapStepInput>(
    hub: Hub,
    hogTransformer: HogTransformerService
): ProcessingStep<TInput, EventPipelineRunnerHeatmapStepResult> {
    return async function eventPipelineRunnerHeatmapStep(
        input: TInput
    ): Promise<PipelineResult<EventPipelineRunnerHeatmapStepResult>> {
        const { normalizedEvent, timestamp, team, headers, personsStoreForBatch, groupStoreForBatch } = input

        const runner = new EventPipelineRunner(
            hub,
            normalizedEvent,
            hogTransformer,
            personsStoreForBatch,
            groupStoreForBatch,
            headers
        )
        const result = await runner.runHeatmapPipeline(normalizedEvent, timestamp, team)
        return result
    }
}
