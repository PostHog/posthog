import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventHeaders, Hub, IncomingEventWithTeam } from '../../types'
import { EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { EventPipelineResult } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResult, isOkResult } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface EventPipelineRunnerInput extends IncomingEventWithTeam {
    headers: EventHeaders
    groupStoreForBatch: GroupStoreForBatch
    processPerson: boolean
    forceDisablePersonProcessing: boolean
}

export function createEventPipelineRunnerV1Step(
    hub: Hub,
    hogTransformer: HogTransformerService,
    personsStore: PersonsStore
): ProcessingStep<EventPipelineRunnerInput, EventPipelineResult> {
    return async function eventPipelineRunnerV1Step(
        input: EventPipelineRunnerInput
    ): Promise<PipelineResult<EventPipelineResult>> {
        const {
            event,
            team,
            headers: inputHeaders,
            message: inputMessage,
            groupStoreForBatch,
            processPerson,
            forceDisablePersonProcessing,
        } = input

        const runner = new EventPipelineRunner(
            hub,
            event,
            hogTransformer,
            personsStore,
            groupStoreForBatch,
            inputHeaders
        )
        const result = await runner.runEventPipeline(event, team, processPerson, forceDisablePersonProcessing)

        // Pass through message and headers for downstream metric recording
        if (isOkResult(result)) {
            result.value.inputHeaders = inputHeaders
            result.value.inputMessage = inputMessage
        }

        return result
    }
}
