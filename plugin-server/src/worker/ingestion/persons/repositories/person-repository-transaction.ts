import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '../../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../../types'
import { CreatePersonResult, MoveDistinctIdsResult } from '../../../../utils/db/db'

export interface PersonRepositoryTransaction {
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

    deletePerson(person: InternalPerson): Promise<TopicMessage[]>

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]>

    moveDistinctIds(source: InternalPerson, target: InternalPerson, limit?: number): Promise<MoveDistinctIdsResult>

    fetchPersonDistinctIds(person: InternalPerson, limit?: number): Promise<string[]>

    addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean>

    updateCohortsAndFeatureFlagsForMerge(
        teamId: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id']
    ): Promise<void>
}
