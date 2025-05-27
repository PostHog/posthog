import { BatchWritingStore } from '../stores/batch-writing-store'
import { GroupStoreForDistinctIdBatch } from './group-store-for-distinct-id-batch'

export interface GroupStoreForBatch extends BatchWritingStore {
    /**
     * Returns an instance of GroupStoreForDistinctIdBatch for handling distinct ID operations
     * @param token - The token (team ID) for the distinct ID operations
     * @param distinctId - The distinct ID to operate on
     */
    forDistinctID(token: string, distinctId: string): GroupStoreForDistinctIdBatch

    /**
     * Reports metrics about group operations in batch
     */
    reportBatch(): void
}
