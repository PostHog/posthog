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

    /**
     * Recover from a PersonPropertiesSizeViolationError thrown by updatePerson by trimming the
     * existing oversized row and re-applying the update. Must not be called while holding a
     * transaction — it acquires its own connections. Throws PersonPropertiesSizeViolationError
     * when remediation is impossible (existing row within limits) or the trimmed retry fails.
     */
    remediateOversizedPersonProperties(
        person: InternalPerson,
        update: PersonUpdateFields
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

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<PersonMessage[]>

    addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean>
    addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean>
    addPersonlessDistinctIdsBatch(entries: { teamId: number; distinctId: string }[]): Promise<Map<string, boolean>>

    personPropertiesSize(personId: string, teamId: number): Promise<number>

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id']
    ): Promise<void>

    inTransaction<T>(description: string, transaction: (tx: PersonRepositoryTransaction) => Promise<T>): Promise<T>
}
