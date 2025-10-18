import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Hub, IncomingEventWithTeam } from '../../types'
import { EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { EventPipelineResult } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStoreForBatch } from '../../worker/ingestion/persons/persons-store-for-batch'
import { PipelineResult } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface HeatmapPipelineRunnerInput extends IncomingEventWithTeam {
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
}

export function createEventPipelineRunnerHeatmapStep(
    hub: Hub,
    hogTransformer: HogTransformerService
): ProcessingStep<HeatmapPipelineRunnerInput, EventPipelineResult> {
    return async function eventPipelineRunnerHeatmapStep(
        input: HeatmapPipelineRunnerInput
    ): Promise<PipelineResult<EventPipelineResult>> {
        const { event, team, headers, personsStoreForBatch, groupStoreForBatch } = input

        const runner = new EventPipelineRunner(
            hub,
            event,
            hogTransformer,
            personsStoreForBatch,
            groupStoreForBatch,
            headers
        )
        const result = await runner.runHeatmapPipeline(event, team)
        return result
    }
}
