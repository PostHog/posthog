import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Hub, IncomingEventWithTeam } from '../../types'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { retryIfRetriable } from '../../utils/retries'
import { EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { EventPipelineResult } from '../../worker/ingestion/event-pipeline/runner'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStoreForBatch } from '../../worker/ingestion/persons/persons-store-for-batch'
import { PipelineResult, dlq } from '../pipelines/results'
import { AsyncProcessingStep } from '../pipelines/steps'

export interface EventPipelineRunnerV1StepInput {
    eventWithTeam: IncomingEventWithTeam
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
}

export interface PreprocessedEventWithStores extends IncomingEventWithTeam {
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
}

function handleProcessingError(error: any): PipelineResult<EventPipelineResult> {
    logger.error('🔥', `Error processing message`, {
        stack: error.stack,
        error: error,
    })

    // If the error is a non-retriable error, capture exception and return DLQ result
    if (error?.isRetriable === false) {
        captureException(error)
        return dlq('Processing error - non-retriable', error)
    } else {
        // For retriable errors, re-throw to be handled by retry logic
        throw error
    }
}

export function createEventPipelineRunnerV1Step(
    hub: Hub,
    hogTransformer: HogTransformerService
): AsyncProcessingStep<PreprocessedEventWithStores, EventPipelineResult> {
    return async function eventPipelineRunnerV1Step(
        input: PreprocessedEventWithStores
    ): Promise<PipelineResult<EventPipelineResult>> {
        const { event, team, headers, personsStoreForBatch, groupStoreForBatch } = input

        try {
            const result = await retryIfRetriable(async () => {
                const runner = new EventPipelineRunner(
                    hub,
                    event,
                    hogTransformer,
                    personsStoreForBatch,
                    groupStoreForBatch,
                    headers
                )
                return await runner.runEventPipeline(event, team)
            })
            return result
        } catch (error) {
            // Handle the error using the same logic as handleProcessingErrorV1
            return handleProcessingError(error)
        }
    }
}
