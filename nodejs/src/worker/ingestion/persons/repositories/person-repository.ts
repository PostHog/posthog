import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'

import {
    InternalPerson,
    PersonUpdateFields,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
    TeamId,
} from '../../../../types'
import { CreatePersonResult } from '../../../../utils/db/db'
import type { PersonMessage } from '../person-message'
import { PersonUpdate } from '../person-update-batch'
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
 * Read-only person lookups. Used by services that only need to fetch person
 * data (CDP, error tracking, future pipelines). Implementations may be
 * backed by personhog gRPC with no Postgres dependency.
 */
export interface PersonReadRepository {
    fetchPerson(teamId: Team['id'], distinctId: string): Promise<InternalPerson | undefined>

    fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[]
    ): Promise<InternalPersonWithDistinctId[]>

    fetchPersonsByPersonIds(teamPersons: { teamId: TeamId; personId: string }[]): Promise<InternalPerson[]>

    fetchDistinctIdsForPersons(
        teamId: TeamId,
        personIntIds: string[],
        options?: { limitPerPerson?: number }
    ): Promise<Record<string, string[]>>
}

/**
 * Full person repository with read and write operations. Used by the
 * ingestion pipeline which creates, updates, merges, and deletes persons.
 * Extends PersonReadRepository so ingestion code can also perform lookups.
 */
export interface PersonRepository extends PersonReadRepository {
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
