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

export interface GroupRepositoryTransaction {
    fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<Group | undefined>

    fetchGroupsByKeys(
        teamIds: TeamId[],
        groupTypeIndexes: GroupTypeIndex[],
        groupKeys: string[]
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
        propertiesLastOperation: PropertiesLastOperation
    ): Promise<number>

    updateGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        tag: string
    ): Promise<number | undefined>

    // Group Type Methods

    fetchGroupTypesByProjectIds(
        projectIds: ProjectId[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>>

    fetchGroupTypesByTeamIds(
        teamIds: TeamId[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>>

    insertGroupType(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string,
        index: number
    ): Promise<[GroupTypeIndex | null, boolean]>
}
