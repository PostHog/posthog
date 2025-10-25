import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { BatchWritingPersonsStore } from '../../worker/ingestion/persons/batch-writing-person-store'
import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../pipelines/results'

export interface AddBatchStoresStepConfig {
    personStore: BatchWritingPersonsStore
    groupStore: BatchWritingGroupStore
}

export type AddBatchStoresStepOutput<T> = T & {
    personsStoreForBatch: ReturnType<BatchWritingPersonsStore['forBatch']>
    groupStoreForBatch: ReturnType<BatchWritingGroupStore['forBatch']>
}

/**
 * Adds batch stores to each event in the batch.
 * This step creates batch-level stores from the main stores and injects them into each event
 * so that downstream steps can access them for person and group operations.
 */
export function createAddBatchStoresStep<T>(
    config: AddBatchStoresStepConfig
): BatchProcessingStep<T, AddBatchStoresStepOutput<T>> {
    return function addBatchStoresStep(inputs: T[]): Promise<PipelineResult<AddBatchStoresStepOutput<T>>[]> {
        const personsStoreForBatch = config.personStore.forBatch()
        const groupStoreForBatch = config.groupStore.forBatch()

        return Promise.resolve(
            inputs.map((input) =>
                ok({
                    ...input,
                    personsStoreForBatch,
                    groupStoreForBatch,
                })
            )
        )
    }
}
