import { DateTime } from 'luxon'
import { QueryResult } from 'pg'

import { Properties } from '@posthog/plugin-scaffold'

import { sanitizeJsonbValue } from '~/utils/db/utils'

import {
    Group,
    GroupTypeIndex,
    ProjectId,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    RawGroup,
    TeamId,
} from '../../../../types'
import { PostgresRouter, PostgresUse, TransactionClient } from '../../../../utils/db/postgres'
import { RaceConditionError } from '../../../../utils/utils'
import { GroupRepositoryTransaction } from './group-repository-transaction.interface'
import { GroupRepository } from './group-repository.interface'
import { PostgresGroupRepositoryTransaction } from './postgres-group-repository-transaction'
import { RawPostgresGroupRepository } from './raw-postgres-group-repository.interface'

const MAX_GROUP_TYPES_PER_TEAM = 5

export class PostgresGroupRepository
    implements GroupRepository, RawPostgresGroupRepository, GroupRepositoryTransaction
{
    constructor(public postgres: PostgresRouter) {}

    async fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options: { forUpdate?: boolean; useReadReplica?: boolean } = {},
        tx?: TransactionClient
    ): Promise<Group | undefined> {
        if (options.forUpdate && options.useReadReplica) {
            throw new Error("can't enable both forUpdate and useReadReplica in fetchGroup")
        }

        let queryString = `SELECT * FROM posthog_group WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3`

        if (options.forUpdate) {
            queryString = queryString.concat(` FOR UPDATE`)
        }

        const selectResult: QueryResult = await this.postgres.query(
            tx ?? (options.useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE),
            queryString,
            [teamId, groupTypeIndex, groupKey],
            'fetchGroup'
        )

        if (selectResult.rows.length > 0) {
            const rawGroup: RawGroup = selectResult.rows[0]
            return this.toGroup(rawGroup)
        }
    }

    async fetchGroupsByKeys(
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
    > {
        if (teamIds.length === 0 || groupTypeIndexes.length === 0 || groupKeys.length === 0) {
            return []
        }

        const { rows } = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_READ,
            `SELECT team_id, group_type_index, group_key, group_properties
             FROM posthog_group
             WHERE team_id = ANY($1) AND group_type_index = ANY($2) AND group_key = ANY($3)`,
            [teamIds, groupTypeIndexes, groupKeys],
            'fetchGroupsByKeys'
        )

        return rows.map((row) => {
            if (row.group_type_index < 0 || row.group_type_index > 4) {
                throw new Error(
                    `Invalid group_type_index ${row.group_type_index} for team ${row.team_id}. Must be between 0 and 4.`
                )
            }

            return {
                team_id: row.team_id as TeamId,
                group_type_index: row.group_type_index as GroupTypeIndex,
                group_key: row.group_key,
                group_properties: row.group_properties,
            }
        })
    }

    async insertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        tx?: TransactionClient
    ): Promise<number> {
        const result = await this.postgres.query<{ version: string }>(
            tx ?? PostgresUse.PERSONS_WRITE,
            `
            INSERT INTO posthog_group (team_id, group_key, group_type_index, group_properties, created_at, properties_last_updated_at, properties_last_operation, version)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (team_id, group_key, group_type_index) DO NOTHING
            RETURNING version
            `,
            [
                teamId,
                groupKey,
                groupTypeIndex,
                sanitizeJsonbValue(groupProperties),
                createdAt.toISO(),
                JSON.stringify(propertiesLastUpdatedAt),
                JSON.stringify(propertiesLastOperation),
                1,
            ],
            'insertGroup'
        )

        if (result.rows.length === 0) {
            throw new RaceConditionError('Parallel posthog_group inserts, retry')
        }

        return Number(result.rows[0].version || 0)
    }

    async updateGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        tag: string,
        tx?: TransactionClient
    ): Promise<number | undefined> {
        const result = await this.postgres.query<{ version: string }>(
            tx ?? PostgresUse.PERSONS_WRITE,
            `
            UPDATE posthog_group SET
            created_at = $4,
            group_properties = $5,
            properties_last_updated_at = $6,
            properties_last_operation = $7,
            version = COALESCE(version, 0)::numeric + 1
            WHERE team_id = $1 AND group_key = $2 AND group_type_index = $3
            RETURNING version
            `,
            [
                teamId,
                groupKey,
                groupTypeIndex,
                createdAt.toISO(),
                sanitizeJsonbValue(groupProperties),
                JSON.stringify(propertiesLastUpdatedAt),
                JSON.stringify(propertiesLastOperation),
            ],
            tag
        )

        if (result.rows.length === 0) {
            return undefined
        }

        return Number(result.rows[0].version || 0)
    }

    async updateGroupOptimistically(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        expectedVersion: number,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation
    ): Promise<number | undefined> {
        const result = await this.postgres.query<{ version: string }>(
            PostgresUse.PERSONS_WRITE,
            `
            UPDATE posthog_group SET
            created_at = $5,
            group_properties = $6,
            properties_last_updated_at = $7,
            properties_last_operation = $8,
            version = COALESCE(version, 0)::numeric + 1
            WHERE team_id = $1 AND group_key = $2 AND group_type_index = $3 AND version = $4
            RETURNING version
            `,
            [
                teamId,
                groupKey,
                groupTypeIndex,
                expectedVersion,
                createdAt.toISO(),
                sanitizeJsonbValue(groupProperties),
                JSON.stringify(propertiesLastUpdatedAt),
                JSON.stringify(propertiesLastOperation),
            ],
            'updateGroupOptimistically'
        )

        if (result.rows.length === 0) {
            return undefined
        }

        return Number(result.rows[0].version || 0)
    }

    async fetchGroupTypesByProjectIds(
        projectIds: ProjectId[],
        tx?: TransactionClient
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        if (projectIds.length === 0) {
            return {}
        }

        const { rows } = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_READ,
            `SELECT project_id, group_type, group_type_index FROM posthog_grouptypemapping WHERE project_id = ANY($1)`,
            [projectIds],
            'fetchGroupTypesByProjectIds'
        )

        const response: Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]> = {}

        // Initialize empty arrays for all requested project IDs
        for (const projectId of projectIds) {
            response[projectId.toString()] = []
        }

        // Group the results by project_id
        for (const row of rows) {
            const projectIdStr = row.project_id.toString()
            if (!response[projectIdStr]) {
                response[projectIdStr] = []
            }

            if (row.group_type_index < 0 || row.group_type_index > 4) {
                throw new Error(
                    `Invalid group_type_index ${row.group_type_index} for team ${row.team_id}, project ${row.project_id}. Must be between 0 and 4.`
                )
            }

            response[projectIdStr].push({
                group_type: row.group_type,
                group_type_index: row.group_type_index as GroupTypeIndex,
            })
        }

        return response
    }

    async fetchGroupTypesByTeamIds(
        teamIds: TeamId[],
        tx?: TransactionClient
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        if (teamIds.length === 0) {
            return {}
        }

        const { rows } = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_READ,
            `SELECT team_id, group_type, group_type_index FROM posthog_grouptypemapping WHERE team_id = ANY($1)`,
            [teamIds],
            'fetchGroupTypesByTeamIds'
        )

        const response: Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]> = {}

        for (const teamId of teamIds) {
            response[teamId.toString()] = []
        }

        for (const row of rows) {
            const teamIdStr = row.team_id.toString()
            if (!response[teamIdStr]) {
                response[teamIdStr] = []
            }

            if (row.group_type_index < 0 || row.group_type_index > 4) {
                throw new Error(
                    `Invalid group_type_index ${row.group_type_index} for team ${row.team_id}. Must be between 0 and 4.`
                )
            }

            response[teamIdStr].push({
                group_type: row.group_type,
                group_type_index: row.group_type_index as GroupTypeIndex,
            })
        }

        return response
    }

    async insertGroupType(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string,
        index: number,
        tx?: TransactionClient
    ): Promise<[GroupTypeIndex | null, boolean]> {
        if (index < 0 || index >= MAX_GROUP_TYPES_PER_TEAM) {
            return [null, false]
        }

        const insertGroupTypeResult = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
            `
            WITH insert_result AS (
                INSERT INTO posthog_grouptypemapping (team_id, project_id, group_type, group_type_index, created_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT DO NOTHING
                RETURNING group_type_index
            )
            SELECT group_type_index, 1 AS is_insert FROM insert_result
            UNION
            SELECT group_type_index, 0 AS is_insert FROM posthog_grouptypemapping WHERE project_id = $2 AND group_type = $3;
            `,
            [teamId, projectId, groupType, index, new Date()],
            'insertGroupType'
        )

        if (insertGroupTypeResult.rows.length == 0) {
            return await this.insertGroupType(teamId, projectId, groupType, index + 1, tx)
        }

        const { group_type_index, is_insert } = insertGroupTypeResult.rows[0]
        return [group_type_index, is_insert === 1]
    }

    async inTransaction<T>(
        description: string,
        transaction: (tx: GroupRepositoryTransaction) => Promise<T>
    ): Promise<T> {
        return await this.inRawTransaction(description, async (tx: TransactionClient) => {
            const transactionClient = new PostgresGroupRepositoryTransaction(tx, this)
            return await transaction(transactionClient)
        })
    }

    async inRawTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T> {
        return await this.postgres.transaction(PostgresUse.PERSONS_WRITE, description, transaction)
    }

    private toGroup(row: RawGroup): Group {
        return {
            ...row,
            created_at: DateTime.fromISO(row.created_at).toUTC(),
            version: Number(row.version || 0),
        }
    }
}
