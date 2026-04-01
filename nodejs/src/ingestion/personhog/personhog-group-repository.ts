import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'

import { Group, GroupTypeIndex, ProjectId, PropertiesLastOperation, PropertiesLastUpdatedAt, TeamId } from '../../types'
import { logger } from '../../utils/logger'
import { GroupRepositoryTransaction } from '../../worker/ingestion/groups/repositories/group-repository-transaction.interface'
import { GroupRepository } from '../../worker/ingestion/groups/repositories/group-repository.interface'
import { PersonHogClient, shouldUseGrpc } from './client'
import { timedGrpc, timedPostgres } from './metrics'

export class PersonHogGroupRepository implements GroupRepository {
    constructor(
        private postgres: GroupRepository,
        private grpcClient: PersonHogClient,
        private grpcPercentage: number,
        private clientLabel: string
    ) {}

    async fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<Group | undefined> {
        // Only route to gRPC for eventually-consistent replica reads (useReadReplica: true)
        // where no row-level lock is needed (forUpdate: false/unset).
        if (options?.forUpdate || !options?.useReadReplica || !shouldUseGrpc(this.grpcPercentage)) {
            return timedPostgres(this.clientLabel, 'fetchGroup', () =>
                this.postgres.fetchGroup(teamId, groupTypeIndex, groupKey, options)
            )
        }

        try {
            return await timedGrpc(this.clientLabel, 'fetchGroup', () =>
                this.grpcClient.groups.fetchGroup(teamId, groupTypeIndex, groupKey)
            )
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchGroup failed, falling back to Postgres', {
                teamId,
                groupTypeIndex,
                error: String(error),
            })
            return timedPostgres(this.clientLabel, 'fetchGroup', () =>
                this.postgres.fetchGroup(teamId, groupTypeIndex, groupKey, options)
            )
        }
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
        if (!shouldUseGrpc(this.grpcPercentage)) {
            return timedPostgres(this.clientLabel, 'fetchGroupsByKeys', () =>
                this.postgres.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys)
            )
        }

        try {
            return await timedGrpc(this.clientLabel, 'fetchGroupsByKeys', () =>
                this.grpcClient.groups.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys)
            )
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchGroupsByKeys failed, falling back to Postgres', {
                count: teamIds.length,
                error: String(error),
            })
            return timedPostgres(this.clientLabel, 'fetchGroupsByKeys', () =>
                this.postgres.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys)
            )
        }
    }

    async fetchGroupTypesByTeamIds(
        teamIds: TeamId[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        if (!shouldUseGrpc(this.grpcPercentage)) {
            return timedPostgres(this.clientLabel, 'fetchGroupTypesByTeamIds', () =>
                this.postgres.fetchGroupTypesByTeamIds(teamIds)
            )
        }

        try {
            return await timedGrpc(this.clientLabel, 'fetchGroupTypesByTeamIds', () =>
                this.grpcClient.groups.fetchGroupTypesByTeamIds(teamIds)
            )
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchGroupTypesByTeamIds failed, falling back to Postgres', {
                count: teamIds.length,
                error: String(error),
            })
            return timedPostgres(this.clientLabel, 'fetchGroupTypesByTeamIds', () =>
                this.postgres.fetchGroupTypesByTeamIds(teamIds)
            )
        }
    }

    async fetchGroupTypesByProjectIds(
        projectIds: ProjectId[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        if (!shouldUseGrpc(this.grpcPercentage)) {
            return timedPostgres(this.clientLabel, 'fetchGroupTypesByProjectIds', () =>
                this.postgres.fetchGroupTypesByProjectIds(projectIds)
            )
        }

        try {
            return await timedGrpc(this.clientLabel, 'fetchGroupTypesByProjectIds', () =>
                this.grpcClient.groups.fetchGroupTypesByProjectIds(projectIds)
            )
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchGroupTypesByProjectIds failed, falling back to Postgres', {
                count: projectIds.length,
                error: String(error),
            })
            return timedPostgres(this.clientLabel, 'fetchGroupTypesByProjectIds', () =>
                this.postgres.fetchGroupTypesByProjectIds(projectIds)
            )
        }
    }

    // All write operations delegate directly to Postgres

    insertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation
    ): Promise<number> {
        return this.postgres.insertGroup(
            teamId,
            groupTypeIndex,
            groupKey,
            groupProperties,
            createdAt,
            propertiesLastUpdatedAt,
            propertiesLastOperation
        )
    }

    updateGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        tag: string
    ): Promise<number | undefined> {
        return this.postgres.updateGroup(
            teamId,
            groupTypeIndex,
            groupKey,
            groupProperties,
            createdAt,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            tag
        )
    }

    updateGroupOptimistically(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        expectedVersion: number,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation
    ): Promise<number | undefined> {
        return this.postgres.updateGroupOptimistically(
            teamId,
            groupTypeIndex,
            groupKey,
            expectedVersion,
            groupProperties,
            createdAt,
            propertiesLastUpdatedAt,
            propertiesLastOperation
        )
    }

    insertGroupType(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string,
        index: number
    ): Promise<[GroupTypeIndex | null, boolean]> {
        return this.postgres.insertGroupType(teamId, projectId, groupType, index)
    }

    inTransaction<T>(description: string, transaction: (tx: GroupRepositoryTransaction) => Promise<T>): Promise<T> {
        return this.postgres.inTransaction(description, transaction)
    }
}
