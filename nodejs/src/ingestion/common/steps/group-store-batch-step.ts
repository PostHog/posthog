import { BatchWritingGroupStore } from '~/ingestion/common/groups/batch-writing-group-store'
import { BatchBoundGroupStore, GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { BeforeBatchStep } from '~/ingestion/framework/batching-pipeline'
import { ok } from '~/ingestion/framework/results'

export interface GroupStoreBatchContext {
    groupStoreForBatch: GroupStoreForBatch
}

export function createGroupStoreBeforeBatchStep<TInput, CInput, CBatch>(
    groupStore: BatchWritingGroupStore
): BeforeBatchStep<TInput, CInput, CBatch, CBatch & GroupStoreBatchContext> {
    return function groupStoreBeforeBatchStep(input) {
        const groupStoreForBatch: GroupStoreForBatch = new BatchBoundGroupStore(groupStore, input.batchContext.batchId)
        const batchContext = { ...input.batchContext, groupStoreForBatch }
        return Promise.resolve(ok({ elements: input.elements, batchContext }))
    }
}
