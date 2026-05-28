import { PersonsStore } from '../../../worker/ingestion/persons/persons-store'
import { BatchBoundPersonsStore, PersonsStoreForBatch } from '../../../worker/ingestion/persons/persons-store-for-batch'
import { BeforeBatchInput, BeforeBatchOutput } from '../../pipelines/batching-pipeline'
import { OkResultWithContext } from '../../pipelines/pipeline.interface'
import { PipelineResult, ok } from '../../pipelines/results'
import { EventFiltersBatchContext } from './event-filters-steps'

export interface IngestionBatchContext extends EventFiltersBatchContext {
    personsStoreForBatch: PersonsStoreForBatch
}

/**
 * BeforeBatch step that creates a batch-bound PersonsStore and attaches it to
 * the batch context and each element value.
 *
 * Must run after createEventFiltersBatchAppMetricsBeforeBatchStep so that
 * EventFiltersBatchContext is already present on elements and batchContext.
 */
export function createPersonsStoreBeforeBatchStep(personsStore: PersonsStore) {
    return function personsStoreBeforeBatchStep<TInput extends EventFiltersBatchContext, CInput>(
        input: BeforeBatchInput<TInput, CInput>
    ): Promise<PipelineResult<BeforeBatchOutput<TInput, CInput, IngestionBatchContext>>> {
        const personsStoreForBatch: PersonsStoreForBatch = new BatchBoundPersonsStore(
            personsStore,
            input.batchContext.batchId
        )
        const batchContext = { ...input.batchContext, personsStoreForBatch } as IngestionBatchContext & {
            batchId: number
        }
        const elements = input.elements.map((element) => ({
            result: {
                ...element.result,
                value: { ...element.result.value, personsStoreForBatch },
            },
            context: element.context,
        })) as OkResultWithContext<TInput & IngestionBatchContext, CInput>[]

        return Promise.resolve(ok({ elements, batchContext }))
    }
}
