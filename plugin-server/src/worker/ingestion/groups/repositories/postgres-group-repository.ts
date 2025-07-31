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
            throw new Error("can't enable both forUpdate and useReadReplica in db::fetchGroup")
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

    insertGroup(
        _teamId: TeamId,
        _groupTypeIndex: GroupTypeIndex,
        _groupKey: string,
        _groupProperties: Properties,
        _createdAt: DateTime,
        _propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        _propertiesLastOperation: PropertiesLastOperation,
        _tx?: TransactionClient
    ): Promise<number> {
        throw new Error('insertGroup not implemented yet')
    }

    updateGroup(
        _teamId: TeamId,
        _groupTypeIndex: GroupTypeIndex,
        _groupKey: string,
        _groupProperties: Properties,
        _createdAt: DateTime,
        _propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        _propertiesLastOperation: PropertiesLastOperation,
        _tag: string,
        _tx?: TransactionClient
    ): Promise<number | undefined> {
        throw new Error('updateGroup not implemented yet')
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
        throw new Error('updateGroupOptimistically not implemented yet')
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
