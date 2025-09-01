import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import {
    Group,
    GroupTypeIndex,
    ProjectId,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    TeamId,
} from '../../../../types'
import { TransactionClient } from '../../../../utils/db/postgres'
import { dualWriteComparisonCounter, dualWriteDataMismatchCounter } from '../../persons/metrics'
import { GroupRepositoryTransaction } from './group-repository-transaction.interface'
import { RawPostgresGroupRepository } from './raw-postgres-group-repository.interface'

export class DualWriteGroupRepositoryTransaction implements GroupRepositoryTransaction {
    constructor(
        private primaryRepo: RawPostgresGroupRepository,
        private secondaryRepo: RawPostgresGroupRepository,
        private lTx: TransactionClient,
        private rTx: TransactionClient,
        private comparisonEnabled: boolean = false
    ) {}

    async fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<Group | undefined> {
        return await this.primaryRepo.fetchGroup(teamId, groupTypeIndex, groupKey, options, this.lTx)
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
        // For read operations, only query the primary repository
        return await this.primaryRepo.fetchGroupsByKeys(teamIds, groupTypeIndexes, groupKeys, this.lTx)
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
        const [p, s] = await Promise.all([
            this.primaryRepo.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                this.lTx
            ),
            this.secondaryRepo.insertGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                this.rTx
            ),
        ])

        if (this.comparisonEnabled) {
            this.compareInsertGroupResults(p, s)
        }

        return p
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
        const p = await this.primaryRepo.updateGroup(
            teamId,
            groupTypeIndex,
            groupKey,
            groupProperties,
            createdAt,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            tag,
            this.lTx
        )

        if (p !== undefined) {
            const s = await this.secondaryRepo.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                `${tag}-secondary`,
                this.rTx
            )

            if (this.comparisonEnabled) {
                this.compareUpdateGroupResults(p, s, tag)
            }
        }

        return p
    }

    private compareInsertGroupResults(primary: number, secondary: number): void {
        if (primary !== secondary) {
            dualWriteDataMismatchCounter.inc({ operation: 'insertGroup_tx', field: 'version' })
            dualWriteComparisonCounter.inc({
                operation: 'insertGroup_tx',
                comparison_type: 'version_mismatch',
                result: 'mismatch',
            })
        } else {
            dualWriteComparisonCounter.inc({
                operation: 'insertGroup_tx',
                comparison_type: 'version_match',
                result: 'match',
            })
        }
    }

    private compareUpdateGroupResults(primary: number | undefined, secondary: number | undefined, tag: string): void {
        if (primary !== secondary) {
            if (primary === undefined || secondary === undefined) {
                dualWriteComparisonCounter.inc({
                    operation: `updateGroup_tx:${tag}`,
                    comparison_type: 'existence_mismatch',
                    result: 'mismatch',
                })
            } else {
                dualWriteDataMismatchCounter.inc({ operation: `updateGroup_tx:${tag}`, field: 'version' })
                dualWriteComparisonCounter.inc({
                    operation: `updateGroup_tx:${tag}`,
                    comparison_type: 'version_mismatch',
                    result: 'mismatch',
                })
            }
        } else {
            dualWriteComparisonCounter.inc({
                operation: `updateGroup_tx:${tag}`,
                comparison_type: 'version_match',
                result: 'match',
            })
        }
    }

    async fetchGroupTypesByProjectIds(
        projectIds: ProjectId[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        // For read operations, only query the primary repository
        return await this.primaryRepo.fetchGroupTypesByProjectIds(projectIds, this.lTx)
    }

    async fetchGroupTypesByTeamIds(
        teamIds: TeamId[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        // For read operations, only query the primary repository
        return await this.primaryRepo.fetchGroupTypesByTeamIds(teamIds, this.lTx)
    }

    async insertGroupType(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string,
        index: number
    ): Promise<[GroupTypeIndex | null, boolean]> {
        const [primaryResult, secondaryResult] = await Promise.all([
            this.primaryRepo.insertGroupType(teamId, projectId, groupType, index, this.lTx),
            this.secondaryRepo.insertGroupType(teamId, projectId, groupType, index, this.rTx),
        ])

        const [primaryIndex, primaryIsInsert] = primaryResult
        const [secondaryIndex, secondaryIsInsert] = secondaryResult

        if (primaryIndex !== secondaryIndex || primaryIsInsert !== secondaryIsInsert) {
            dualWriteDataMismatchCounter.inc({ operation: 'insertGroupType_tx', field: 'result' })
        } else {
            dualWriteComparisonCounter.inc({
                operation: 'insertGroupType_tx',
                comparison_type: 'result_match',
                result: 'match',
            })
        }

        return primaryResult
    }
}
