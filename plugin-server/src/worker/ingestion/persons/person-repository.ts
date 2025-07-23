import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt } from '../../../types'
import { MoveDistinctIdsResult } from '../../../utils/db/db'
import { TransactionClient } from '../../../utils/db/postgres'

export interface PersonRepository {
    fetchPerson(
        teamId: number,
        distinctId: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<InternalPerson | undefined>

    createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        distinctIds?: { distinctId: string; version?: number }[],
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]>

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

    addPersonlessDistinctId(teamId: number, distinctId: string): Promise<boolean>
    addPersonlessDistinctIdForMerge(teamId: number, distinctId: string, tx?: TransactionClient): Promise<boolean>
}
