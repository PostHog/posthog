import { PersonsStoreForDistinctIdBatch } from './persons-store-for-distinct-id-batch'

export interface PersonsStoreForBatch {
    /**
     * Returns an instance of PersonsStoreForDistinctID for handling distinct ID operations
     * @param token - The token (team ID) for the distinct ID operations
     * @param distinctId - The distinct ID to operate on
     */
    forDistinctID(token: string, distinctId: string): PersonsStoreForDistinctIdBatch

    /**
     * Reports metrics about person operations in batch
     */
    reportBatch(): void
}
