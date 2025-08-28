import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { Group, GroupTypeIndex, PropertiesLastOperation, PropertiesLastUpdatedAt, TeamId } from '../../../../types'
import { TransactionClient } from '../../../../utils/db/postgres'
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
}
