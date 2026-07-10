import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'
import { Group, GroupTypeIndex, ProjectId, PropertiesLastOperation, PropertiesLastUpdatedAt, TeamId } from '~/types'

import { GroupRepositoryTransaction } from './group-repository-transaction.interface'

/**
 * Read-only group lookups backed by personhog gRPC. Used by services that
 * only need to fetch group data (CDP, error tracking). Always uses eventual
 * consistency. Independent of GroupRepository — the two interfaces have
 * different parameter shapes reflecting their different backends and consumers.
 */
export interface GroupReadRepository {
    fetchGroupsByKeys(
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
        }[]
    >

    fetchGroupTypesByTeamIds(
        teamIds: TeamId[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>>

    fetchGroupTypesByProjectIds(
        projectIds: ProjectId[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>>
}

/**
 * A batched, merge-semantics group update: `propertiesToSet` is applied on top
 * of the stored `group_properties` server-side (jsonb `||`), so concurrent
 * writers can't lose each other's keys and no version assertion is needed.
 */
export interface GroupPropertiesToSetUpdate {
    teamId: TeamId
    groupTypeIndex: GroupTypeIndex
    groupKey: string
    propertiesToSet: Properties
    createdAt: DateTime
}

/**
 * Full group repository with read and write operations. Used by the
 * ingestion pipeline which creates, updates, and manages groups.
 * Postgres-backed with support for consistency control and row locking.
 */
export interface GroupRepository {
    fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean; callerTag?: string }
    ): Promise<Group | undefined>

    fetchGroupsByKeys(
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
    >

    /**
     * Applies all updates in a single statement and returns the updated rows.
     * Rows whose group doesn't exist are absent from the result — callers
     * handle those individually (typically by creating the group).
     */
    updateGroupsBatch(updates: GroupPropertiesToSetUpdate[]): Promise<Group[]>

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
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>>

    fetchGroupTypesByTeamIds(
        teamIds: TeamId[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>>

    insertGroupType(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string,
        index: number,
        createdAt: DateTime
    ): Promise<[GroupTypeIndex | null, boolean]>

    // Transaction Methods

    inTransaction<T>(description: string, transaction: (tx: GroupRepositoryTransaction) => Promise<T>): Promise<T>
}
