import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '../../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team, TeamId } from '../../../../types'
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
        teamPersons: { teamId: TeamId; distinctId: string }[]
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
        distinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult>

    updatePerson(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tag?: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]>

    updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]>

    deletePerson(person: InternalPerson): Promise<TopicMessage[]>

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]>

    addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean>
    addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean>

    personPropertiesSize(personId: string): Promise<number>

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id']
    ): Promise<void>

    inTransaction<T>(description: string, transaction: (tx: PersonRepositoryTransaction) => Promise<T>): Promise<T>
}
