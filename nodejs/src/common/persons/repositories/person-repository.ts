import { DateTime } from 'luxon'

import type { PersonMessage } from '~/common/persons/person-message'
import { PersonUpdate } from '~/common/persons/person-update-batch'
import { CreatePersonResult } from '~/common/utils/db/db'
import { Properties } from '~/plugin-scaffold'
import {
    InternalPerson,
    PersonUpdateFields,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
    TeamId,
} from '~/types'

import { PersonRepositoryTransaction } from './person-repository-transaction'

export type { PersonMessage }

export type InternalPersonWithDistinctId = InternalPerson & {
    distinct_id: string
}

export class PersonPropertiesSizeViolationError extends Error {
    constructor(
        message: string,
        public teamId: number,
        public personId?: string,
        public distinctId?: string
    ) {
        super(message)
        this.name = 'PersonPropertiesSizeViolationError'
    }
    readonly isRetriable = false
}

export class DistinctIdConflictError extends Error {
    constructor(
        message: string,
        public teamId: number,
        public distinctId?: string
    ) {
        super(message)
        this.name = 'DistinctIdConflictError'
    }
}

/**
 * A tombstone delete found live distinct id rows still pointing at the person
 * (a concurrent merge added or moved them in after ours moved the known set).
 * The tombstone-mode equivalent of the FK violation a hard delete would raise;
 * callers refresh the person and retry, re-moving the new rows.
 */
export class PersonTombstoneBlockedError extends Error {
    constructor(
        message: string,
        public teamId: number
    ) {
        super(message)
        this.name = 'PersonTombstoneBlockedError'
    }
}

/**
 * A lifecycle-mark claim lost to a live claim by another operation (a delete
 * saga mid-flight, or a concurrent merge on the same event). At most one live
 * operation may hold a person; callers back off and retry, by which time the
 * winner has usually finished.
 */
export class PersonClaimedByLifecycleOpError extends Error {
    constructor(
        message: string,
        public teamId: number
    ) {
        super(message)
        this.name = 'PersonClaimedByLifecycleOpError'
    }
}

/** A person a merge claims in the lifecycle mark table for the duration of its transaction. */
export interface LifecycleMarkPerson {
    personId: string
    personUuid: string
    role: 'target' | 'source'
    ordinal?: number
}

/**
 * Read-only person lookups backed by personhog gRPC. Used by services that
 * only need to fetch person data (CDP, error tracking, future pipelines).
 * Always uses eventual consistency. Independent of PersonRepository — the
 * two interfaces have different parameter shapes reflecting their different
 * backends and consumers.
 */
export interface PersonReadRepository {
    fetchPerson(teamId: Team['id'], distinctId: string, callerTag?: string): Promise<InternalPerson | undefined>

    fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[],
        callerTag?: string
    ): Promise<InternalPersonWithDistinctId[]>

    fetchPersonsByPersonIds(
        teamPersons: { teamId: TeamId; personId: string }[],
        callerTag?: string
    ): Promise<InternalPerson[]>

    fetchDistinctIdsForPersons(
        teamId: TeamId,
        personIntIds: string[],
        options?: { limitPerPerson?: number },
        callerTag?: string
    ): Promise<Record<string, string[]>>
}

/**
 * Full person repository with read and write operations. Used by the
 * ingestion pipeline which creates, updates, merges, and deletes persons.
 * Postgres-backed with support for consistency control and row locking.
 */
export interface PersonRepository {
    fetchPerson(
        teamId: Team['id'],
        distinctId: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean; callerTag?: string }
    ): Promise<InternalPerson | undefined>

    fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[],
        useReadReplica?: boolean,
        callerTag?: string
    ): Promise<InternalPersonWithDistinctId[]>

    fetchPersonsByPersonIds(
        teamPersons: { teamId: TeamId; personId: string }[],
        useReadReplica?: boolean,
        callerTag?: string
    ): Promise<InternalPerson[]>

    /**
     * Batched, row-locking variant of fetchPerson({forUpdate: true}) for folded
     * merges: resolves and locks all persons behind the given distinct_ids in
     * one statement, in deterministic (person id) lock order.
     */
    fetchPersonsForUpdateByDistinctIds(
        teamId: TeamId,
        distinctIds: string[],
        callerTag?: string
    ): Promise<InternalPersonWithDistinctId[]>

    /**
     * Fetch up to ``limitPerPerson`` distinct_ids for each given int person_id (single team).
     * Returns a record keyed by int person_id as a string (matching InternalPerson.id).
     * Persons with no distinct_ids will be absent from the result.
     */
    fetchDistinctIdsForPersons(
        teamId: TeamId,
        personIntIds: string[],
        options?: { limitPerPerson?: number; useReadReplica?: boolean }
    ): Promise<Record<string, string[]>>

    createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: Team['id'],
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult>

    updatePerson(
        person: InternalPerson,
        update: PersonUpdateFields,
        tag?: string
    ): Promise<[InternalPerson, PersonMessage[], boolean]>

    updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, PersonMessage[]]>

    /**
     * Batch update multiple persons in a single query using UNNEST.
     * Returns results indexed by person UUID, each containing:
     * - success: boolean indicating if the update succeeded
     * - version: the new version if successful
     * - kafkaMessage: the Kafka message to send if successful
     * - error: error details if the update failed
     */
    updatePersonsBatch(
        personUpdates: PersonUpdate[]
    ): Promise<Map<string, { success: boolean; version?: number; kafkaMessage?: PersonMessage; error?: Error }>>

    deletePerson(person: InternalPerson): Promise<PersonMessage[]>

    /** Batched deletePerson for folded merges; all persons must belong to one team. */
    deletePersons(persons: InternalPerson[]): Promise<PersonMessage[]>

    /**
     * Claims the given persons in the lifecycle mark table for a merge: at most one live
     * operation (merge or delete saga) may hold a person, enforced by the mark index.
     * Claim before reading state the transaction relies on, and hold until commit via
     * releaseLifecycleMarks. Throws PersonClaimedByLifecycleOpError when another
     * operation holds one of the persons.
     */
    claimLifecycleMarks(opId: string, teamId: number, persons: LifecycleMarkPerson[]): Promise<void>

    /** Releases a merge's lifecycle marks; must run in the same transaction as the claim. */
    releaseLifecycleMarks(opId: string, teamId: number): Promise<void>

    /**
     * Whether the person row exists and is not tombstoned. Only meaningful while the
     * caller holds the person's lifecycle mark: the mark excludes concurrent tombstones,
     * so the answer stays true until the transaction commits.
     */
    isPersonLive(person: InternalPerson): Promise<boolean>

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<PersonMessage[]>

    personPropertiesSize(personId: string, teamId: number): Promise<number>

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id']
    ): Promise<void>

    updateCohortsAndFeatureFlagsForMergeBatch(
        teamID: Team['id'],
        sourcePersonIDs: InternalPerson['id'][],
        targetPersonID: InternalPerson['id']
    ): Promise<void>

    inTransaction<T>(description: string, transaction: (tx: PersonRepositoryTransaction) => Promise<T>): Promise<T>
}
