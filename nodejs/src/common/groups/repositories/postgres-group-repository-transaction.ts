import { DateTime } from 'luxon'

import { TransactionClient } from '~/common/utils/db/postgres'
import { Properties } from '~/plugin-scaffold'
import { Group, GroupTypeIndex, ProjectId, PropertiesLastOperation, PropertiesLastUpdatedAt, TeamId } from '~/types'

import { GroupRepositoryTransaction } from './group-repository-transaction.interface'
import { RawPostgresGroupRepository } from './raw-postgres-group-repository.interface'

export class PostgresGroupRepositoryTransaction implements GroupRepositoryTransaction {
    constructor(
        private tx: TransactionClient,
        private repository: RawPostgresGroupRepository
    ) {}

    async fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options: { forUpdate?: boolean; useReadReplica?: boolean } = {}
    ): Promise<Group | undefined> {
        return await this.repository.fetchGroup(teamId, groupTypeIndex, groupKey, options, this.tx)
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
        return await this.repository.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys, undefined, this.tx)
    }

    async insertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation
    ): Promise<number> {
        return await this.repository.insertGroup(
            teamId,
            groupTypeIndex,
            groupKey,
            groupProperties,
            createdAt,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            this.tx
        )
    }

    async updateGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        tag: string
    ): Promise<number | undefined> {
        return await this.repository.updateGroup(
            teamId,
            groupTypeIndex,
            groupKey,
            groupProperties,
            createdAt,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            tag,
            this.tx
        )
    }

    async fetchGroupTypesByProjectIds(
        projectIds: ProjectId[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        return await this.repository.fetchGroupTypesByProjectIds(projectIds, undefined, this.tx)
    }

    async fetchGroupTypesByTeamIds(
        teamIds: TeamId[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        return await this.repository.fetchGroupTypesByTeamIds(teamIds, undefined, this.tx)
    }

    async insertGroupType(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string,
        index: number,
        createdAt: DateTime
    ): Promise<[GroupTypeIndex | null, boolean]> {
        return await this.repository.insertGroupType(teamId, projectId, groupType, index, createdAt, this.tx)
    }
}
