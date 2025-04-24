import { PersonsStoreForBatch } from './persons-store-for-batch'

export interface PersonsStore {
    /**
     * Returns an instance of BatchPersonsStore for handling person operations in batch
     */
    forBatch(): PersonsStoreForBatch
}
