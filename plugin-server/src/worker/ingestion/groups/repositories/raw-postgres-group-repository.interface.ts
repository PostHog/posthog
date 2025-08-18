import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { Group, GroupTypeIndex, PropertiesLastOperation, PropertiesLastUpdatedAt, TeamId } from '../../../../types'
import { TransactionClient } from '../../../../utils/db/postgres'

export interface RawPostgresGroupRepository {
    fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean },
        tx?: TransactionClient
    ): Promise<Group | undefined>

    insertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        tx?: TransactionClient
    ): Promise<number>

    updateGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        tag: string,
        tx?: TransactionClient
    ): Promise<number | undefined>

    updateGroupOptimistically(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        expectedVersion: number,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation
    ): Promise<number | undefined>

    inRawTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T>
}
