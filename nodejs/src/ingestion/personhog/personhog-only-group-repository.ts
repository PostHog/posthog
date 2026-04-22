import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'

import { Group, GroupTypeIndex, ProjectId, PropertiesLastOperation, PropertiesLastUpdatedAt, TeamId } from '../../types'
import { GroupRepositoryTransaction } from '../../worker/ingestion/groups/repositories/group-repository-transaction.interface'
import { GroupRepository } from '../../worker/ingestion/groups/repositories/group-repository.interface'
import { PersonHogClient } from './client'
import { timedGrpc } from './metrics'

export class PersonHogOnlyGroupRepository implements GroupRepository {
    constructor(
        private grpcClient: PersonHogClient,
        private clientLabel: string
    ) {}

    async fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        _options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<Group | undefined> {
        return timedGrpc(this.clientLabel, 'fetchGroup', () =>
            this.grpcClient.groups.fetchGroup(teamId, groupTypeIndex, groupKey)
        )
    }

    async fetchGroupsByKeys(
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
    > {
        return timedGrpc(this.clientLabel, 'fetchGroupsByKeys', () =>
            this.grpcClient.groups.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys)
        )
    }

    async fetchGroupTypesByTeamIds(
        teamIds: TeamId[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        return timedGrpc(this.clientLabel, 'fetchGroupTypesByTeamIds', () =>
            this.grpcClient.groups.fetchGroupTypesByTeamIds(teamIds)
        )
    }

    async fetchGroupTypesByProjectIds(
        projectIds: ProjectId[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        return timedGrpc(this.clientLabel, 'fetchGroupTypesByProjectIds', () =>
            this.grpcClient.groups.fetchGroupTypesByProjectIds(projectIds)
        )
    }

    // Write operations are not supported — CDP services are read-only consumers.

    insertGroup(
        _teamId: TeamId,
        _groupTypeIndex: GroupTypeIndex,
        _groupKey: string,
        _groupProperties: Properties,
        _createdAt: DateTime,
        _propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        _propertiesLastOperation: PropertiesLastOperation
    ): Promise<number> {
        throw new Error('PersonHogOnlyGroupRepository does not support write operations')
    }

    updateGroup(
        _teamId: TeamId,
        _groupTypeIndex: GroupTypeIndex,
        _groupKey: string,
        _groupProperties: Properties,
        _createdAt: DateTime,
        _propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        _propertiesLastOperation: PropertiesLastOperation,
        _tag: string
    ): Promise<number | undefined> {
        throw new Error('PersonHogOnlyGroupRepository does not support write operations')
    }

    updateGroupOptimistically(
        _teamId: TeamId,
        _groupTypeIndex: GroupTypeIndex,
        _groupKey: string,
        _expectedVersion: number,
        _groupProperties: Properties,
        _createdAt: DateTime,
        _propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        _propertiesLastOperation: PropertiesLastOperation
    ): Promise<number | undefined> {
        throw new Error('PersonHogOnlyGroupRepository does not support write operations')
    }

    insertGroupType(
        _teamId: TeamId,
        _projectId: ProjectId,
        _groupType: string,
        _index: number
    ): Promise<[GroupTypeIndex | null, boolean]> {
        throw new Error('PersonHogOnlyGroupRepository does not support write operations')
    }

    inTransaction<T>(_description: string, _transaction: (tx: GroupRepositoryTransaction) => Promise<T>): Promise<T> {
        throw new Error('PersonHogOnlyGroupRepository does not support write operations')
    }
}
