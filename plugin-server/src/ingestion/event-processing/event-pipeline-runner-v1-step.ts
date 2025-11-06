import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Hub, IncomingEventWithTeam, JwtVerificationStatus } from '../../types'
import { EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { EventPipelineResult } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStoreForBatch } from '../../worker/ingestion/persons/persons-store-for-batch'
import { PipelineResult } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface EventPipelineRunnerInput extends IncomingEventWithTeam {
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
    processPerson: boolean
    forceDisablePersonProcessing: boolean
    verified: JwtVerificationStatus
}

export function createEventPipelineRunnerV1Step(
    hub: Hub,
    hogTransformer: HogTransformerService
): ProcessingStep<EventPipelineRunnerInput, EventPipelineResult> {
    return async function eventPipelineRunnerV1Step(
        input: EventPipelineRunnerInput
    ): Promise<PipelineResult<EventPipelineResult>> {
        const {
            event,
            team,
            headers,
            personsStoreForBatch,
            groupStoreForBatch,
            processPerson,
            forceDisablePersonProcessing,
            verified,
        } = input

        const runner = new EventPipelineRunner(
            hub,
            event,
            hogTransformer,
            personsStoreForBatch,
            groupStoreForBatch,
            headers,
            verified
        )
        const result = await runner.runEventPipeline(event, team, processPerson, forceDisablePersonProcessing)
        return result
    }
}
