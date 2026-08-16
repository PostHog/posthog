import { DateTime } from 'luxon'

import { PersonMessage } from '~/common/persons/person-message'
import { InternalPersonWithDistinctId, LifecycleMarkPerson } from '~/common/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/common/utils/db/db'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'

import { EventOps } from './person-update'
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

    /** Claims the persons in the lifecycle mark table until commit; conflicts throw. */
    claimLifecycleMarks(opId: string, teamId: number, persons: LifecycleMarkPerson[], distinctId: string): Promise<void>

    /** Releases a merge's lifecycle marks; same transaction as the claim. */
    releaseLifecycleMarks(opId: string, teamId: number, distinctId: string): Promise<void>

    /** Whether the person is live; only meaningful while holding its lifecycle mark. */
    isPersonLive(person: InternalPerson, distinctId: string): Promise<boolean>

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<PersonMessage[]>

    moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit?: number
    ): Promise<MoveDistinctIdsResult>

    /** Batched unlimited moveDistinctIds for folded merges. */
    moveDistinctIdsFromPersons(
        sources: InternalPerson[],
        target: InternalPerson,
        distinctId: string
    ): Promise<MoveDistinctIdsResult>

    /** Batched deletePerson for folded merges; all persons must belong to one team. */
    deletePersons(persons: InternalPerson[], distinctId: string): Promise<PersonMessage[]>

    /** Distinct-id counts per person id, for the folded-merge limit pre-check. */
    countDistinctIdsForPersons(
        teamId: Team['id'],
        personIds: InternalPerson['id'][],
        distinctId: string
    ): Promise<Map<string, number>>

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string
    ): Promise<void>

    updateCohortsAndFeatureFlagsForMergeBatch(
        teamID: Team['id'],
        sourcePersonIDs: InternalPerson['id'][],
        targetPersonID: InternalPerson['id'],
        distinctId: string
    ): Promise<void>

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
    | 'fetchPersonsForUpdateByDistinctIds'
    | 'applyEventOps'
    | 'createPerson'
    | 'updatePersonForMerge'
    | 'updatePersonWithPropertiesDiffForUpdate'
    | 'addDistinctId'
    | 'moveDistinctIds'
    | 'moveDistinctIdsFromPersons'
    | 'prefetchPersons'
    | 'releaseBatch'
    | 'getFlushStats'
    | 'inTransaction'
> & {
    fetchForChecking(teamId: number, distinctId: string): Promise<InternalPerson | null>
    fetchForUpdate(teamId: number, distinctId: string): Promise<InternalPerson | null>
    fetchPersonsForUpdateByDistinctIds(teamId: number, distinctIds: string[]): Promise<InternalPersonWithDistinctId[]>
    applyEventOps(person: InternalPerson, ops: EventOps, distinctId: string): Promise<[InternalPerson, PersonMessage[]]>
    moveDistinctIdsFromPersons(
        sources: InternalPerson[],
        target: InternalPerson,
        distinctId: string,
        tx: PersonRepositoryTransaction
    ): Promise<MoveDistinctIdsResult>
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
    moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction
    ): Promise<MoveDistinctIdsResult>
    prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void>
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

    claimLifecycleMarks(
        opId: string,
        teamId: number,
        persons: LifecycleMarkPerson[],
        distinctId: string
    ): Promise<void> {
        return this.tx.claimLifecycleMarks(opId, teamId, persons, distinctId)
    }

    releaseLifecycleMarks(opId: string, teamId: number, distinctId: string): Promise<void> {
        return this.tx.releaseLifecycleMarks(opId, teamId, distinctId)
    }

    isPersonLive(person: InternalPerson, distinctId: string): Promise<boolean> {
        return this.tx.isPersonLive(person, distinctId)
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

    moveDistinctIdsFromPersons(
        sources: InternalPerson[],
        target: InternalPerson,
        distinctId: string
    ): Promise<MoveDistinctIdsResult> {
        return this.tx.moveDistinctIdsFromPersons(sources, target, distinctId, this.batchId)
    }

    deletePersons(persons: InternalPerson[], distinctId: string): Promise<PersonMessage[]> {
        return this.tx.deletePersons(persons, distinctId)
    }

    countDistinctIdsForPersons(
        teamId: Team['id'],
        personIds: InternalPerson['id'][],
        distinctId: string
    ): Promise<Map<string, number>> {
        return this.tx.countDistinctIdsForPersons(teamId, personIds, distinctId)
    }

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string
    ): Promise<void> {
        return this.tx.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, distinctId)
    }

    updateCohortsAndFeatureFlagsForMergeBatch(
        teamID: Team['id'],
        sourcePersonIDs: InternalPerson['id'][],
        targetPersonID: InternalPerson['id'],
        distinctId: string
    ): Promise<void> {
        return this.tx.updateCohortsAndFeatureFlagsForMergeBatch(teamID, sourcePersonIDs, targetPersonID, distinctId)
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

    applyEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string
    ): Promise<[InternalPerson, PersonMessage[]]> {
        return this.store.applyEventOps(person, ops, distinctId, this.batchId)
    }

    fetchForUpdate(teamId: number, distinctId: string): Promise<InternalPerson | null> {
        return this.store.fetchForUpdate(teamId, distinctId, this.batchId)
    }

    fetchPersonsForUpdateByDistinctIds(teamId: number, distinctIds: string[]): Promise<InternalPersonWithDistinctId[]> {
        return this.store.fetchPersonsForUpdateByDistinctIds(teamId, distinctIds, this.batchId)
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

    moveDistinctIdsFromPersons(
        sources: InternalPerson[],
        target: InternalPerson,
        distinctId: string,
        tx: PersonRepositoryTransaction
    ): Promise<MoveDistinctIdsResult> {
        return this.store.moveDistinctIdsFromPersons(sources, target, distinctId, tx, this.batchId)
    }

    deletePersons(
        persons: InternalPerson[],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<PersonMessage[]> {
        return this.store.deletePersons(persons, distinctId, tx)
    }

    countDistinctIdsForPersons(
        teamId: Team['id'],
        personIds: InternalPerson['id'][],
        distinctId: string,
        tx: PersonRepositoryTransaction
    ): Promise<Map<string, number>> {
        return this.store.countDistinctIdsForPersons(teamId, personIds, distinctId, tx)
    }

    updateCohortsAndFeatureFlagsForMergeBatch(
        teamID: Team['id'],
        sourcePersonIDs: InternalPerson['id'][],
        targetPersonID: InternalPerson['id'],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return this.store.updateCohortsAndFeatureFlagsForMergeBatch(
            teamID,
            sourcePersonIDs,
            targetPersonID,
            distinctId,
            tx
        )
    }

    prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void> {
        return this.store.prefetchPersons(teamDistinctIds)
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

    claimLifecycleMarks(
        opId: string,
        teamId: number,
        persons: LifecycleMarkPerson[],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return this.store.claimLifecycleMarks(opId, teamId, persons, distinctId, tx)
    }

    releaseLifecycleMarks(
        opId: string,
        teamId: number,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return this.store.releaseLifecycleMarks(opId, teamId, distinctId, tx)
    }

    isPersonLive(person: InternalPerson, distinctId: string, tx?: PersonRepositoryTransaction): Promise<boolean> {
        return this.store.isPersonLive(person, distinctId, tx)
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

    flush(): Promise<FlushResult[]> {
        return this.store.flush()
    }

    shutdown(): Promise<void> {
        return this.store.shutdown()
    }
}
