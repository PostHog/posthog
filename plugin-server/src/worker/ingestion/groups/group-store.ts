import { GroupStoreForBatch } from './group-store-for-batch'

export interface GroupStore {
    /**
     * Returns an instance of GroupStoreForBatch for handling group operations in batch
     */
    forBatch(): GroupStoreForBatch
}
