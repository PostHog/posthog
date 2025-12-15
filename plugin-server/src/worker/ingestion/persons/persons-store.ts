import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { CreatePersonResult, MoveDistinctIdsResult } from '../../../utils/db/db'
import { BatchWritingStore } from '../stores/batch-writing-store'
import { PersonsStoreTransaction } from './persons-store-transaction'
import { PersonRepositoryTransaction } from './repositories/person-repository-transaction'

export type FlushResult = {
    topicMessage: TopicMessage
    teamId: number
    distinctId?: string
    uuid?: string
}

export interface PersonsStore extends BatchWritingStore {
    /**
     * Executes a function within a transaction
     * @param description - Description of the transaction for logging
     * @param transaction - Function to execute within the transaction, receives a transaction interface
     */
    inTransaction<T>(description: string, transaction: (tx: PersonsStoreTransaction) => Promise<T>): Promise<T>

    /**
     * Fetches a person by team ID and distinct ID for checking existence
     * Uses read replica when available
     */
    fetchForChecking(teamId: number, distinctId: string): Promise<InternalPerson | null>

    /**
     * Fetches a person by team ID and distinct ID with a row-level lock
     * Always uses primary database
     */
    fetchForUpdate(teamId: number, distinctId: string): Promise<InternalPerson | null>

    /**
     * Creates a new person
     */
    createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds?: { distinctId: string; version?: number }[],
        tx?: PersonRepositoryTransaction
    ): Promise<CreatePersonResult>

    /**
     * Updates an existing person for merge operations
     */
    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, TopicMessage[], boolean]>

    /**
     * Updates person for regular updates with specific properties to set and unset
     */
    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        forceUpdate?: boolean,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, TopicMessage[], boolean]>

    /**
     * Deletes a person
     */
    deletePerson(person: InternalPerson, distinctId: string, tx?: PersonRepositoryTransaction): Promise<TopicMessage[]>

    /**
     * Adds a distinct ID to a person
     */
    addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: PersonRepositoryTransaction
    ): Promise<TopicMessage[]>

    /**
     * Moves distinct IDs from one person to another
     */
    moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction
    ): Promise<MoveDistinctIdsResult>

    /**
     * Updates cohorts and feature flags for merged persons
     */
    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void>

    /**
     * Adds a personless distinct ID
     */
    addPersonlessDistinctId(teamId: number, distinctId: string): Promise<boolean>

    /**
     * Adds a personless distinct ID during merge
     */
    addPersonlessDistinctIdForMerge(
        teamId: number,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<boolean>

    /**
     * Returns the size of the person properties
     */
    personPropertiesSize(personId: string, teamId: number): Promise<number>

    /**
     * Fetch distinct ids for a person inside a transaction-aware wrapper
     */
    fetchPersonDistinctIds(
        person: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction
    ): Promise<string[]>

    /**
     * Reports metrics about person operations in batch
     */
    reportBatch(): void

    /**
     * Resets the batch store state, clearing all caches and metrics.
     * Should be called after flush() to prepare for the next batch.
     */
    reset(): void

    /**
     * Removes a distinct ID from the cache
     */
    removeDistinctIdFromCache(teamId: number, distinctId: string): void

    /**
     * Prefetches persons by team ID and distinct ID to warm up the cache
     * @param teamDistinctIds - A list of team IDs and distinct IDs to prefetch
     */
    prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string }[]): Promise<void>

    /**
     * Batch-inserts personless distinct IDs for events where no person exists.
     * Stores is_merged results in a cache for later lookup.
     * @param entries - A list of team IDs and distinct IDs to insert
     */
    processPersonlessDistinctIdsBatch(entries: { teamId: number; distinctId: string }[]): Promise<void>

    /**
     * Gets the is_merged result from batch personless insert.
     * Returns undefined if not in batch cache.
     */
    getPersonlessBatchResult(teamId: number, distinctId: string): boolean | undefined

    /**
     * Flushes the batch
     */
    flush(): Promise<FlushResult[]>
}
