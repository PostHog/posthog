import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import {
    Group,
    GroupTypeIndex,
    ProjectId,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    TeamId,
} from '../../../../types'
import { TransactionClient } from '../../../../utils/db/postgres'

export interface RawPostgresGroupRepository {
    fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean },
        tx?: TransactionClient
    ): Promise<Group | undefined>

    fetchGroupsByKeys(
        teamIds: TeamId[],
        groupTypeIndexes: GroupTypeIndex[],
        groupKeys: string[],
        tx?: TransactionClient
    ): Promise<
        {
            team_id: TeamId
            group_type_index: GroupTypeIndex
            group_key: string
            group_properties: Record<string, any>
        }[]
    >

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

    // Group Type Methods

    fetchGroupTypesByProjectIds(
        projectIds: ProjectId[],
        tx?: TransactionClient
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>>

    fetchGroupTypesByTeamIds(
        teamIds: TeamId[],
        tx?: TransactionClient
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>>

    insertGroupType(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string,
        index: number,
        tx?: TransactionClient
    ): Promise<[GroupTypeIndex | null, boolean]>

    // Transaction Methods

    inRawTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T>
}
