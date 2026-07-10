import { DateTime } from 'luxon'

import { GroupRepositoryTransaction } from '~/common/groups/repositories/group-repository-transaction.interface'
import { GroupPropertiesToSetUpdate, GroupRepository } from '~/common/groups/repositories/group-repository.interface'
import { logger } from '~/common/utils/logger'
import { Properties } from '~/plugin-scaffold'
import { Group, GroupTypeIndex, ProjectId, PropertiesLastOperation, PropertiesLastUpdatedAt, TeamId } from '~/types'

import { PersonHogClient, shouldUseGrpc, shouldUseGrpcForTeam, shouldUseGrpcForTeams } from './client'
import { timedGrpc, timedPostgres } from './metrics'

export class PersonHogGroupRepository implements GroupRepository {
    constructor(
        private postgres: GroupRepository,
        private grpcClient: PersonHogClient,
        private grpcPercentage: number,
        private rolloutTeamIds: ReadonlySet<number>,
        private clientLabel: string
    ) {}

    async fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean; callerTag?: string }
    ): Promise<Group | undefined> {
        // Only route to gRPC for eventually-consistent replica reads (useReadReplica: true)
        // where no row-level lock is needed (forUpdate: false/unset).
        if (
            options?.forUpdate ||
            !options?.useReadReplica ||
            !shouldUseGrpcForTeam(this.rolloutTeamIds, teamId, this.grpcPercentage)
        ) {
            return timedPostgres(this.clientLabel, 'fetchGroup', () =>
                this.postgres.fetchGroup(teamId, groupTypeIndex, groupKey, options)
            )
        }

        try {
            return await timedGrpc(this.clientLabel, 'fetchGroup', () =>
                this.grpcClient.groups.fetchGroup(teamId, groupTypeIndex, groupKey, options?.callerTag)
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
        groupKeys: string[],
        callerTag?: string
    ): Promise<
        {
            team_id: TeamId
            group_type_index: GroupTypeIndex
            group_key: string
            group_properties: Record<string, any>
            created_at: DateTime
            version: number
        }[]
    > {
        if (!shouldUseGrpcForTeams(this.rolloutTeamIds, teamIds, this.grpcPercentage)) {
            return timedPostgres(this.clientLabel, 'fetchGroupsByKeys', () =>
                this.postgres.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys, callerTag)
            )
        }

        try {
            return await timedGrpc(this.clientLabel, 'fetchGroupsByKeys', () =>
                this.grpcClient.groups.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys, callerTag)
            )
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchGroupsByKeys failed, falling back to Postgres', {
                count: teamIds.length,
                error: String(error),
            })
            return timedPostgres(this.clientLabel, 'fetchGroupsByKeys', () =>
                this.postgres.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys, callerTag)
            )
        }
    }

    async fetchGroupTypesByTeamIds(
        teamIds: TeamId[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        if (!shouldUseGrpcForTeams(this.rolloutTeamIds, teamIds, this.grpcPercentage)) {
            return timedPostgres(this.clientLabel, 'fetchGroupTypesByTeamIds', () =>
                this.postgres.fetchGroupTypesByTeamIds(teamIds, callerTag)
            )
        }

        try {
            return await timedGrpc(this.clientLabel, 'fetchGroupTypesByTeamIds', () =>
                this.grpcClient.groups.fetchGroupTypesByTeamIds(teamIds, callerTag)
            )
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchGroupTypesByTeamIds failed, falling back to Postgres', {
                count: teamIds.length,
                error: String(error),
            })
            return timedPostgres(this.clientLabel, 'fetchGroupTypesByTeamIds', () =>
                this.postgres.fetchGroupTypesByTeamIds(teamIds, callerTag)
            )
        }
    }

    async fetchGroupTypesByProjectIds(
        projectIds: ProjectId[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        if (!shouldUseGrpc(this.grpcPercentage)) {
            return timedPostgres(this.clientLabel, 'fetchGroupTypesByProjectIds', () =>
                this.postgres.fetchGroupTypesByProjectIds(projectIds, callerTag)
            )
        }

        try {
            return await timedGrpc(this.clientLabel, 'fetchGroupTypesByProjectIds', () =>
                this.grpcClient.groups.fetchGroupTypesByProjectIds(projectIds, callerTag)
            )
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchGroupTypesByProjectIds failed, falling back to Postgres', {
                count: projectIds.length,
                error: String(error),
            })
            return timedPostgres(this.clientLabel, 'fetchGroupTypesByProjectIds', () =>
                this.postgres.fetchGroupTypesByProjectIds(projectIds, callerTag)
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

    updateGroupsBatch(updates: GroupPropertiesToSetUpdate[]): Promise<Group[]> {
        return this.postgres.updateGroupsBatch(updates)
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
        index: number,
        createdAt: DateTime
    ): Promise<[GroupTypeIndex | null, boolean]> {
        return this.postgres.insertGroupType(teamId, projectId, groupType, index, createdAt)
    }

    inTransaction<T>(description: string, transaction: (tx: GroupRepositoryTransaction) => Promise<T>): Promise<T> {
        return this.postgres.inTransaction(description, transaction)
    }
}
