import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventHeaders, Hub, IncomingEventWithTeam } from '../../types'
import { EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { EventPipelineResult } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResult } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface HeatmapPipelineRunnerInput extends IncomingEventWithTeam {
    headers: EventHeaders
    groupStoreForBatch: GroupStoreForBatch
}

export function createEventPipelineRunnerHeatmapStep(
    hub: Hub,
    hogTransformer: HogTransformerService,
    personsStore: PersonsStore
): ProcessingStep<HeatmapPipelineRunnerInput, EventPipelineResult> {
    return async function eventPipelineRunnerHeatmapStep(
        input: HeatmapPipelineRunnerInput
    ): Promise<PipelineResult<EventPipelineResult>> {
        const { event, team, headers, groupStoreForBatch } = input

        const runner = new EventPipelineRunner(
            hub,
            event,
            hogTransformer,
            personsStore,
            groupStoreForBatch,
            headers
        )
        const result = await runner.runHeatmapPipeline(event, team)
        return result
    }
}
