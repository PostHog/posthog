import { PersonsStoreForBatch } from './persons-store-for-batch'

export interface PersonsStore {
    /**
     * Returns an instance of PersonsStoreForBatch for handling person operations in batch
     */
    forBatch(): PersonsStoreForBatch
}
