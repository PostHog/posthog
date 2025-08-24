import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { Group, GroupTypeIndex, PropertiesLastOperation, PropertiesLastUpdatedAt, TeamId } from '../../../../types'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { TwoPhaseCommitCoordinator } from '../../../../utils/db/two-phase'
import { logger as _logger } from '../../../../utils/logger'
import { RaceConditionError } from '../../../../utils/utils'
import { dualWriteComparisonCounter, dualWriteDataMismatchCounter } from '../../persons/metrics'
import { DualWriteGroupRepositoryTransaction } from './dualwrite-group-repository-transaction'
import { GroupRepositoryTransaction } from './group-repository-transaction.interface'
import { GroupRepository } from './group-repository.interface'
import { PostgresGroupRepository } from './postgres-group-repository'
import { RawPostgresGroupRepository } from './raw-postgres-group-repository.interface'

export interface PostgresDualWriteGroupRepositoryOptions {
    comparisonEnabled?: boolean
}

export class PostgresDualWriteGroupRepository implements GroupRepository {
    private coordinator: TwoPhaseCommitCoordinator
    private primaryRepo: RawPostgresGroupRepository
    private secondaryRepo: RawPostgresGroupRepository
    private comparisonEnabled: boolean

    constructor(
        primaryRouter: PostgresRouter,
        secondaryRouter: PostgresRouter,
        options?: Partial<PostgresDualWriteGroupRepositoryOptions>
    ) {
        this.primaryRepo = new PostgresGroupRepository(primaryRouter)
        this.secondaryRepo = new PostgresGroupRepository(secondaryRouter)
        this.comparisonEnabled = options?.comparisonEnabled ?? false
        this.coordinator = new TwoPhaseCommitCoordinator({
            left: { router: primaryRouter, use: PostgresUse.PERSONS_WRITE, name: 'primary' },
            right: { router: secondaryRouter, use: PostgresUse.PERSONS_WRITE, name: 'secondary' },
        })
    }

    async fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<Group | undefined> {
        return await this.primaryRepo.fetchGroup(teamId, groupTypeIndex, groupKey, options)
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
        let result!: number
        let raceConditionError: RaceConditionError | null = null

        try {
            await this.coordinator.run('insertGroup', async (leftTx, rightTx) => {
                try {
                    const [p, s] = await Promise.all([
                        this.primaryRepo.insertGroup(
                            teamId,
                            groupTypeIndex,
                            groupKey,
                            groupProperties,
                            createdAt,
                            propertiesLastUpdatedAt,
                            propertiesLastOperation,
                            leftTx
                        ),
                        this.secondaryRepo.insertGroup(
                            teamId,
                            groupTypeIndex,
                            groupKey,
                            groupProperties,
                            createdAt,
                            propertiesLastUpdatedAt,
                            propertiesLastOperation,
                            rightTx
                        ),
                    ])

                    if (this.comparisonEnabled) {
                        this.compareInsertGroupResults(p, s)
                    }

                    result = p
                    return true
                } catch (err) {
                    if (err instanceof RaceConditionError) {
                        raceConditionError = err
                        return false
                    }
                    throw err
                }
            })
        } catch (err) {
            if (raceConditionError) {
                throw raceConditionError
            }
            throw err
        }

        if (raceConditionError) {
            throw raceConditionError
        }

        return result
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
        let primaryOut!: number | undefined
        await this.coordinator.run(`updateGroup:${tag}`, async (leftTx, rightTx) => {
            const p = await this.primaryRepo.updateGroup(
                teamId,
                groupTypeIndex,
                groupKey,
                groupProperties,
                createdAt,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                tag,
                leftTx
            )
            primaryOut = p

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
                    rightTx
                )

                if (this.comparisonEnabled) {
                    this.compareUpdateGroupResults(p, s, tag)
                }
            }

            return true
        })
        return primaryOut
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
        const primaryResult = await this.primaryRepo.updateGroupOptimistically(
            teamId,
            groupTypeIndex,
            groupKey,
            expectedVersion,
            groupProperties,
            createdAt,
            propertiesLastUpdatedAt,
            propertiesLastOperation
        )

        if (primaryResult !== undefined) {
            try {
                const secondaryResult = await this.secondaryRepo.updateGroupOptimistically(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    expectedVersion,
                    groupProperties,
                    createdAt,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation
                )

                if (this.comparisonEnabled) {
                    if (primaryResult !== secondaryResult) {
                        dualWriteComparisonCounter.inc({
                            operation: 'updateGroupOptimistically',
                            comparison_type: 'version_mismatch',
                            result: 'mismatch',
                        })
                    } else {
                        dualWriteComparisonCounter.inc({
                            operation: 'updateGroupOptimistically',
                            comparison_type: 'version_match',
                            result: 'match',
                        })
                    }
                }
            } catch (err) {
                _logger.error('Failed to update secondary in optimistic update', {
                    error: err,
                    teamId,
                    groupKey,
                    groupTypeIndex,
                })
            }
        }

        return primaryResult
    }

    async inTransaction<T>(
        description: string,
        transaction: (tx: GroupRepositoryTransaction) => Promise<T>
    ): Promise<T> {
        let result!: T
        let raceConditionError: RaceConditionError | null = null

        try {
            await this.coordinator.run(`dual-tx:${description}`, async (lTx, rTx) => {
                const txWrapper = new DualWriteGroupRepositoryTransaction(
                    this.primaryRepo,
                    this.secondaryRepo,
                    lTx,
                    rTx,
                    this.comparisonEnabled
                )
                try {
                    result = await transaction(txWrapper)
                    return true
                } catch (err) {
                    if (err instanceof RaceConditionError) {
                        raceConditionError = err
                        return false
                    }
                    throw err
                }
            })
        } catch (err: any) {
            if (raceConditionError) {
                throw raceConditionError
            }
            throw err
        }

        if (raceConditionError) {
            throw raceConditionError
        }

        return result
    }

    private compareInsertGroupResults(primary: number, secondary: number): void {
        if (primary !== secondary) {
            dualWriteDataMismatchCounter.inc({ operation: 'insertGroup', field: 'version' })
            dualWriteComparisonCounter.inc({
                operation: 'insertGroup',
                comparison_type: 'version_mismatch',
                result: 'mismatch',
            })
        } else {
            dualWriteComparisonCounter.inc({
                operation: 'insertGroup',
                comparison_type: 'version_match',
                result: 'match',
            })
        }
    }

    private compareUpdateGroupResults(primary: number | undefined, secondary: number | undefined, tag: string): void {
        if (primary !== secondary) {
            if (primary === undefined || secondary === undefined) {
                dualWriteComparisonCounter.inc({
                    operation: `updateGroup:${tag}`,
                    comparison_type: 'existence_mismatch',
                    result: 'mismatch',
                })
            } else {
                dualWriteDataMismatchCounter.inc({ operation: `updateGroup:${tag}`, field: 'version' })
                dualWriteComparisonCounter.inc({
                    operation: `updateGroup:${tag}`,
                    comparison_type: 'version_mismatch',
                    result: 'mismatch',
                })
            }
        } else {
            dualWriteComparisonCounter.inc({
                operation: `updateGroup:${tag}`,
                comparison_type: 'version_match',
                result: 'match',
            })
        }
    }
}
