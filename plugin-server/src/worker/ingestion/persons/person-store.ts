import { PersonsStoreForDistinctID } from './distinct-id-person-store'

export interface PersonsStore {
    /**
     * Returns an instance of PersonsStoreForDistinctID for handling distinct ID operations
     * @param teamId - The team ID for the distinct ID operations
     * @param distinctId - The distinct ID to operate on
     */
    forDistinctID(teamId: number, distinctId: string): PersonsStoreForDistinctID

    /**
     * Reports metrics about person operations
     */
    reportMetrics(): Promise<void>
}
