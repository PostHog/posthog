import { DateTime } from 'luxon'

import { PersonMessage } from '~/common/persons/person-message'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/common/utils/db/db'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'

import { FlushResult, PersonsStore } from './persons-store'
import { PersonsStoreTransaction } from './persons-store-transaction'

export interface PersonsStoreTransactionForBatch {
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
        extraDistinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult>

    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string
    ): Promise<[InternalPerson, PersonMessage[], boolean]>

    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        forceUpdate?: boolean
    ): Promise<[InternalPerson, PersonMessage[], boolean]>

    deletePerson(person: InternalPerson, distinctId: string): Promise<PersonMessage[]>

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<PersonMessage[]>

    moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit?: number
    ): Promise<MoveDistinctIdsResult>

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string
    ): Promise<void>

    addPersonlessDistinctIdForMerge(teamId: number, distinctId: string): Promise<boolean>

    fetchPersonDistinctIds(person: InternalPerson, distinctId: string, limit?: number): Promise<string[]>
}

/**
 * A view of PersonsStore with batchId bound at construction time.
 * Created once per batch in the BeforeBatch hook and flows into element values
 * via batchContext, eliminating batchId? from individual step method signatures.
 *
 * Excludes root lifecycle helpers that need the underlying singleton store directly,
 * but retains flush/shutdown so callers can flush buffered writes after processing.
 */
export type PersonsStoreForBatch = Omit<
    PersonsStore,
    | 'fetchForChecking'
    | 'fetchForUpdate'
    | 'createPerson'
    | 'updatePersonForMerge'
    | 'updatePersonWithPropertiesDiffForUpdate'
    | 'addDistinctId'
    | 'moveDistinctIds'
    | 'addPersonlessDistinctId'
    | 'addPersonlessDistinctIdForMerge'
    | 'prefetchPersons'
    | 'processPersonlessDistinctIdsBatch'
    | 'releaseBatch'
    | 'getFlushStats'
    | 'inTransaction'
> & {
    fetchForChecking(teamId: number, distinctId: string): Promise<InternalPerson | null>
    fetchForUpdate(teamId: number, distinctId: string): Promise<InternalPerson | null>
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
        extraDistinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult>
    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]>
    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        forceUpdate?: boolean,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]>
    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<PersonMessage[]>
    addPersonlessDistinctId(teamId: number, distinctId: string): Promise<boolean>
    addPersonlessDistinctIdForMerge(
        teamId: number,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<boolean>
    moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction
    ): Promise<MoveDistinctIdsResult>
    prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void>
    processPersonlessDistinctIdsBatch(entries: { teamId: number; distinctId: string }[]): Promise<void>
    inTransaction<T>(description: string, transaction: (tx: PersonsStoreTransactionForBatch) => Promise<T>): Promise<T>
    readonly batchId: number
}

class BatchBoundPersonsStoreTransaction implements PersonsStoreTransactionForBatch {
    constructor(
        private readonly tx: PersonsStoreTransaction,
        private readonly batchId: number
    ) {}

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
        extraDistinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult> {
        return this.tx.createPerson(
            createdAt,
            properties,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            primaryDistinctId,
            extraDistinctIds,
            this.batchId
        )
    }

    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return this.tx.updatePersonForMerge(person, update, distinctId, this.batchId)
    }

    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        forceUpdate?: boolean
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return this.tx.updatePersonWithPropertiesDiffForUpdate(
            person,
            propertiesToSet,
            propertiesToUnset,
            otherUpdates,
            distinctId,
            this.batchId,
            forceUpdate
        )
    }

    deletePerson(person: InternalPerson, distinctId: string): Promise<PersonMessage[]> {
        return this.tx.deletePerson(person, distinctId)
    }

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<PersonMessage[]> {
        return this.tx.addDistinctId(person, distinctId, version, this.batchId)
    }

    moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit?: number
    ): Promise<MoveDistinctIdsResult> {
        return this.tx.moveDistinctIds(source, target, distinctId, limit, this.batchId)
    }

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string
    ): Promise<void> {
        return this.tx.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, distinctId)
    }

    addPersonlessDistinctIdForMerge(teamId: number, distinctId: string): Promise<boolean> {
        return this.tx.addPersonlessDistinctIdForMerge(teamId, distinctId, this.batchId)
    }

    fetchPersonDistinctIds(person: InternalPerson, distinctId: string, limit?: number): Promise<string[]> {
        return this.tx.fetchPersonDistinctIds(person, distinctId, limit)
    }
}

export class BatchBoundPersonsStore implements PersonsStoreForBatch {
    constructor(
        private readonly store: PersonsStore,
        public readonly batchId: number
    ) {}

    fetchForChecking(teamId: number, distinctId: string): Promise<InternalPerson | null> {
        return this.store.fetchForChecking(teamId, distinctId, this.batchId)
    }

    fetchForUpdate(teamId: number, distinctId: string): Promise<InternalPerson | null> {
        return this.store.fetchForUpdate(teamId, distinctId, this.batchId)
    }

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
        extraDistinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult> {
        return this.store.createPerson(
            createdAt,
            properties,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            primaryDistinctId,
            extraDistinctIds,
            undefined,
            this.batchId
        )
    }

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<PersonMessage[]> {
        return this.store.addDistinctId(person, distinctId, version, undefined, this.batchId)
    }

    moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction
    ): Promise<MoveDistinctIdsResult> {
        return this.store.moveDistinctIds(source, target, distinctId, limit, tx, this.batchId)
    }

    prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void> {
        return this.store.prefetchPersons(teamDistinctIds)
    }

    processPersonlessDistinctIdsBatch(entries: { teamId: number; distinctId: string }[]): Promise<void> {
        return this.store.processPersonlessDistinctIdsBatch(entries, this.batchId)
    }

    inTransaction<T>(
        description: string,
        transaction: (tx: PersonsStoreTransactionForBatch) => Promise<T>
    ): Promise<T> {
        return this.store.inTransaction(description, (tx) =>
            transaction(new BatchBoundPersonsStoreTransaction(tx, this.batchId))
        )
    }

    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return this.store.updatePersonForMerge(person, update, distinctId, this.batchId, tx)
    }

    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        forceUpdate?: boolean,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return this.store.updatePersonWithPropertiesDiffForUpdate(
            person,
            propertiesToSet,
            propertiesToUnset,
            otherUpdates,
            distinctId,
            this.batchId,
            forceUpdate,
            tx
        )
    }

    deletePerson(
        person: InternalPerson,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<PersonMessage[]> {
        return this.store.deletePerson(person, distinctId, tx)
    }

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return this.store.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, distinctId, tx)
    }

    addPersonlessDistinctId(teamId: number, distinctId: string): Promise<boolean> {
        return this.store.addPersonlessDistinctId(teamId, distinctId, this.batchId)
    }

    addPersonlessDistinctIdForMerge(
        teamId: number,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<boolean> {
        return this.store.addPersonlessDistinctIdForMerge(teamId, distinctId, tx, this.batchId)
    }

    personPropertiesSize(personId: string, teamId: number): Promise<number> {
        return this.store.personPropertiesSize(personId, teamId)
    }

    fetchPersonDistinctIds(
        person: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction
    ): Promise<string[]> {
        return this.store.fetchPersonDistinctIds(person, distinctId, limit, tx)
    }

    removeDistinctIdFromCache(teamId: number, distinctId: string): void {
        return this.store.removeDistinctIdFromCache(teamId, distinctId)
    }

    getPersonlessBatchResult(teamId: number, distinctId: string): boolean | undefined {
        return this.store.getPersonlessBatchResult(teamId, distinctId)
    }

    flush(): Promise<FlushResult[]> {
        return this.store.flush()
    }

    shutdown(): Promise<void> {
        return this.store.shutdown()
    }
}
