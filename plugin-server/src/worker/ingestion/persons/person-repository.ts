import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { MoveDistinctIdsResult } from '../../../utils/db/db'
import { TransactionClient } from '../../../utils/db/postgres'
import { PersonUpdate } from './person-update-batch'

export interface PersonRepository {
    fetchPerson(
        teamId: Team['id'],
        distinctId: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<InternalPerson | undefined>

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
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]>

    updatePerson(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tx?: TransactionClient,
        tag?: string
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
        tx?: TransactionClient
    ): Promise<MoveDistinctIdsResult>

    addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean>
    addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string, tx?: TransactionClient): Promise<boolean>

    personPropertiesSize(teamId: Team['id'], distinctId: string): Promise<number>

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        tx?: TransactionClient
    ): Promise<void>
}
