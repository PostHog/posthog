import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '../../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team, TeamId } from '../../../../types'
import { CreatePersonResult, MoveDistinctIdsResult } from '../../../../utils/db/db'
import { TransactionClient } from '../../../../utils/db/postgres'
import { PersonUpdate } from '../person-update-batch'
import { InternalPersonWithDistinctId } from './person-repository'

export interface RawPostgresPersonRepository {
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
        distinctIds?: { distinctId: string; version?: number }[],
        tx?: TransactionClient,
        forcedId?: number
    ): Promise<CreatePersonResult>

    updatePerson(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tag?: string,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]>

    updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]>

    deletePerson(person: InternalPerson, tx?: TransactionClient): Promise<TopicMessage[]>

    addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]>

    moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        limit?: number,
        tx?: TransactionClient
    ): Promise<MoveDistinctIdsResult>

    fetchPersonDistinctIds(person: InternalPerson, limit?: number, tx?: TransactionClient): Promise<string[]>
    addPersonlessDistinctId(teamId: Team['id'], distinctId: string, tx?: TransactionClient): Promise<boolean>
    addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string, tx?: TransactionClient): Promise<boolean>

    personPropertiesSize(personId: string): Promise<number>

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        tx?: TransactionClient
    ): Promise<void>

    inRawTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T>
}
