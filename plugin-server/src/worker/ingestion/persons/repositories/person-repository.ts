import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '../../../../kafka/producer'
import {
    InternalPerson,
    PersonUpdateFields,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
    TeamId,
} from '../../../../types'
import { CreatePersonResult } from '../../../../utils/db/db'
import { PersonUpdate } from '../person-update-batch'
import { PersonRepositoryTransaction } from './person-repository-transaction'

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

export interface PersonRepository {
    fetchPerson(
        teamId: Team['id'],
        distinctId: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<InternalPerson | undefined>

    fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[],
        useReadReplica?: boolean
    ): Promise<InternalPersonWithDistinctId[]>

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
    ): Promise<[InternalPerson, TopicMessage[], boolean]>

    updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]>

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
    ): Promise<Map<string, { success: boolean; version?: number; kafkaMessage?: TopicMessage; error?: Error }>>

    deletePerson(person: InternalPerson): Promise<TopicMessage[]>

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]>

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
