import { DateTime } from 'luxon'

import { PersonMessage } from '~/common/persons/person-message'
import { InternalPersonWithDistinctId, LifecycleMarkPerson } from '~/common/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/common/utils/db/db'
import { BatchWritingStore } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'

import { EventOps } from './person-update'
import { PersonsStoreTransaction } from './persons-store-transaction'

export type FlushResult = {
    messages: PersonMessage[]
    teamId: number
    distinctId?: string
    uuid?: string
}

export interface PersonsStore extends BatchWritingStore<FlushResult> {
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
    fetchForChecking(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null>

    /**
     * Fetches a person by team ID and distinct ID with a row-level lock
     * Always uses primary database
     */
    fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null>

    /**
     * Batched fetchForUpdate for folded merges: resolves and row-locks all
     * persons behind the given distinct_ids in one statement.
     */
    fetchPersonsForUpdateByDistinctIds(
        teamId: number,
        distinctIds: string[],
        batchId: number
    ): Promise<InternalPersonWithDistinctId[]>

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
        extraDistinctIds: { distinctId: string; version?: number }[] | undefined,
        tx: PersonRepositoryTransaction | undefined,
        batchId: number
    ): Promise<CreatePersonResult>

    /**
     * Updates an existing person for merge operations
     */
    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        batchId: number,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]>

    /**
     * Applies one event's extracted ops to a person, resolving what they
     * mean against this store's own state: snapshot refinement, the
     * identity OR-merge, the last-seen advance, and whether anything is
     * worth writing at all.
     */
    applyEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number
    ): Promise<[InternalPerson, PersonMessage[]]>

    /**
     * Updates person for regular updates with specific properties to set and unset
     */
    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        batchId: number,
        forceUpdate?: boolean,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]>

    /**
     * Deletes a person
     */
    deletePerson(person: InternalPerson, distinctId: string, tx?: PersonRepositoryTransaction): Promise<PersonMessage[]>

    /**
     * Claims the persons in the lifecycle mark table for a merge; at most one live
     * operation may hold a person. Held until the transaction commits.
     */
    claimLifecycleMarks(
        opId: string,
        teamId: number,
        persons: LifecycleMarkPerson[],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void>

    /** Releases a merge's lifecycle marks; same transaction as the claim. */
    releaseLifecycleMarks(
        opId: string,
        teamId: number,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void>

    /** Whether the person is live; only meaningful while holding its lifecycle mark. */
    isPersonLive(person: InternalPerson, distinctId: string, tx?: PersonRepositoryTransaction): Promise<boolean>

    /**
     * Adds a distinct ID to a person
     */
    addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx: PersonRepositoryTransaction | undefined,
        batchId: number
    ): Promise<PersonMessage[]>

    /**
     * Moves distinct IDs from one person to another
     */
    moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction,
        batchId: number
    ): Promise<MoveDistinctIdsResult>

    /**
     * Batched unlimited moveDistinctIds for folded merges
     */
    moveDistinctIdsFromPersons(
        sources: InternalPerson[],
        target: InternalPerson,
        distinctId: string,
        tx: PersonRepositoryTransaction,
        batchId: number
    ): Promise<MoveDistinctIdsResult>

    /**
     * Batched deletePerson for folded merges; all persons must belong to one team
     */
    deletePersons(
        persons: InternalPerson[],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<PersonMessage[]>

    /**
     * Distinct-id counts per person id, for the folded-merge limit pre-check
     */
    countDistinctIdsForPersons(
        teamId: Team['id'],
        personIds: InternalPerson['id'][],
        distinctId: string,
        tx: PersonRepositoryTransaction
    ): Promise<Map<string, number>>

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
     * Batched updateCohortsAndFeatureFlagsForMerge for folded merges
     */
    updateCohortsAndFeatureFlagsForMergeBatch(
        teamID: Team['id'],
        sourcePersonIDs: InternalPerson['id'][],
        targetPersonID: InternalPerson['id'],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void>

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
     * Stop any background work (e.g., periodic metric emission) and flush
     * remaining accumulated metrics. Called on graceful shutdown. Does NOT
     * clear data caches.
     */
    shutdown(): Promise<void>

    /**
     * Removes a distinct ID from the cache
     */
    removeDistinctIdFromCache(teamId: number, distinctId: string): void

    /**
     * Prefetches persons by team ID and distinct ID to warm up the cache.
     * Each entry may carry its own batchId for cache eviction tracking, allowing a
     * single DB fetch to service entries that belong to different concurrent batches.
     * @param teamDistinctIds - A list of team IDs and distinct IDs to prefetch
     */
    prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void>

    /**
     * Flushes the batch
     */
    flush(): Promise<FlushResult[]>

    /**
     * Releases cache entries associated with the given batch ID, using reference
     * counting so entries shared across concurrent batches are only evicted when
     * all referencing batches have completed.
     */
    releaseBatch(batchId: number): void
}
