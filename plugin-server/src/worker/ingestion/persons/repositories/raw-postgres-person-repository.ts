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
        extraDistinctIds?: { distinctId: string; version?: number }[],
        tx?: TransactionClient
    ): Promise<CreatePersonResult>

    updatePerson(
        person: InternalPerson,
        update: PersonUpdateFields,
        tag?: string,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]>

    updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]>

    updatePersonsBatch(
        personUpdates: PersonUpdate[]
    ): Promise<Map<string, { success: boolean; version?: number; kafkaMessage?: TopicMessage; error?: Error }>>

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

    personPropertiesSize(personId: string, teamId: number): Promise<number>

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        tx?: TransactionClient
    ): Promise<void>

    inRawTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T>
}
