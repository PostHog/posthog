import { BeforeBatchStep } from '@posthog/ingestion-common/framework/batching-pipeline'
import { ok } from '@posthog/ingestion-common/framework/results'

import { PersonsStore } from '~/ingestion/common/persons/persons-store'
import { BatchBoundPersonsStore, PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'

export interface PersonsStoreBatchContext {
    personsStoreForBatch: PersonsStoreForBatch
}

/**
 * BeforeBatch step that creates a batch-bound PersonsStore and attaches it to
 * the batch context and each element value.
 *
 * Must run after createEventFiltersBatchAppMetricsBeforeBatchStep so that
 * EventFiltersBatchContext is already present on elements and batchContext.
 */
export function createPersonsStoreBeforeBatchStep<TInput, CInput, CBatch>(
    personsStore: PersonsStore
): BeforeBatchStep<TInput, CInput, CBatch, CBatch & PersonsStoreBatchContext> {
    return async function personsStoreBeforeBatchStep(input) {
        const personsStoreForBatch: PersonsStoreForBatch = new BatchBoundPersonsStore(
            personsStore,
            input.batchContext.batchId
        )
        const batchContext = { ...input.batchContext, personsStoreForBatch }
        return Promise.resolve(ok({ elements: input.elements, batchContext }))
    }
}
