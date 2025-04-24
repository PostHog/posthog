import { PersonsStoreForDistinctIdBatch } from './persons-store-for-distinct-id-batch'

export interface PersonsStoreForBatch {
    /**
     * Returns an instance of PersonsStoreForDistinctID for handling distinct ID operations
     * @param teamId - The team ID for the distinct ID operations
     * @param distinctId - The distinct ID to operate on
     */
    forDistinctID(teamId: number, distinctId: string): PersonsStoreForDistinctIdBatch

    /**
     * Reports metrics about person operations in batch
     */
    reportBatch(): void
}
