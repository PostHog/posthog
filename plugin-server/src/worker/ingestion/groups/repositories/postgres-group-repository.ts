import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { QueryResult } from 'pg'

import {
    Group,
    GroupTypeIndex,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    RawGroup,
    TeamId,
} from '../../../../types'
import { PostgresRouter, PostgresUse, TransactionClient } from '../../../../utils/db/postgres'
import { RaceConditionError } from '../../../../utils/utils'
import { GroupRepository } from './group-repository.interface'
import { GroupRepositoryTransaction } from './group-repository-transaction.interface'
import { PostgresGroupRepositoryTransaction } from './postgres-group-repository-transaction'
import { RawPostgresGroupRepository } from './raw-postgres-group-repository.interface'

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
                JSON.stringify(groupProperties),
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
                JSON.stringify(groupProperties),
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
                JSON.stringify(groupProperties),
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
