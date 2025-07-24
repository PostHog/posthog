import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { MoveDistinctIdsResult } from '../../../utils/db/db'
import { PersonUpdate } from './person-update-batch'

export interface PersonRepositoryTransaction {
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
        distinctIds?: { distinctId: string; version?: number }[]
    ): Promise<[InternalPerson, TopicMessage[]]>

    updatePerson(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tag?: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]>

    updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]>

    deletePerson(person: InternalPerson, distinctId: string): Promise<TopicMessage[]>

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]>

    moveDistinctIds(source: InternalPerson, target: InternalPerson, distinctId: string): Promise<MoveDistinctIdsResult>

    addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean>
    addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean>

    personPropertiesSize(teamId: Team['id'], distinctId: string): Promise<number>

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string
    ): Promise<void>
}
