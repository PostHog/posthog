import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Group, GroupTypeIndex, PropertiesLastOperation, PropertiesLastUpdatedAt, TeamId } from '../../../../types'

export interface GroupRepositoryTransaction {
    fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<Group | undefined>

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
}
