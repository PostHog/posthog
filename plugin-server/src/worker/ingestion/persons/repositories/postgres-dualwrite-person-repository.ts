import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '../../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team, TeamId } from '../../../../types'
import { CreatePersonResult, MoveDistinctIdsResult } from '../../../../utils/db/db'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { TwoPhaseCommitCoordinator } from '../../../../utils/db/two-phase'
import { logger as _logger } from '../../../../utils/logger'
import { dualWriteComparisonCounter, dualWriteDataMismatchCounter } from '../metrics'
import { PersonUpdate } from '../person-update-batch'
import { DualWritePersonRepositoryTransaction } from './dualwrite-person-repository-transaction'
import { InternalPersonWithDistinctId, PersonRepository } from './person-repository'
import { PersonRepositoryTransaction } from './person-repository-transaction'
import type { PostgresPersonRepositoryOptions } from './postgres-person-repository'
import { PostgresPersonRepository } from './postgres-person-repository'
import { RawPostgresPersonRepository } from './raw-postgres-person-repository'

export interface PostgresDualWritePersonRepositoryOptions extends PostgresPersonRepositoryOptions {
    comparisonEnabled?: boolean
}

export class PostgresDualWritePersonRepository implements PersonRepository {
    private coordinator: TwoPhaseCommitCoordinator
    private primaryRepo: RawPostgresPersonRepository
    private secondaryRepo: RawPostgresPersonRepository
    private comparisonEnabled: boolean

    constructor(
        primaryRouter: PostgresRouter,
        secondaryRouter: PostgresRouter,
        options?: Partial<PostgresDualWritePersonRepositoryOptions>
    ) {
        this.primaryRepo = new PostgresPersonRepository(primaryRouter, options)
        this.secondaryRepo = new PostgresPersonRepository(secondaryRouter, options)
        this.comparisonEnabled = options?.comparisonEnabled ?? false
        this.coordinator = new TwoPhaseCommitCoordinator({
            left: { router: primaryRouter, use: PostgresUse.PERSONS_WRITE, name: 'primary' },
            right: { router: secondaryRouter, use: PostgresUse.PERSONS_WRITE, name: 'secondary' },
        })
    }

    // a read, just use the primary as the source of truth (will decide in the underlying logic whether to use reader/writer)
    async fetchPerson(
        teamId: Team['id'],
        distinctId: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<InternalPerson | undefined> {
        return await this.primaryRepo.fetchPerson(teamId, distinctId, options)
    }

    // a read, just use the primary as the source of truth
    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[]
    ): Promise<InternalPersonWithDistinctId[]> {
        return await this.primaryRepo.fetchPersonsByDistinctIds(teamPersons)
    }

    /*
     * needs to have the exact same contract as the single-write repo
     */
    async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: Team['id'],
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        distinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult> {
        let result!: CreatePersonResult
        try {
            await this.coordinator.run('createPerson', async (leftTx, rightTx) => {
                // create is serial: create on primary first, then use returned id the DB generated on secondary
                const p = await this.primaryRepo.createPerson(
                    createdAt,
                    properties,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    teamId,
                    isUserId,
                    isIdentified,
                    uuid,
                    distinctIds,
                    leftTx
                )
                if (!p.success) {
                    result = p
                    throw new Error('DualWrite abort: primary creation conflict')
                }

                // force same id on secondary
                const forcedId = Number(p.person.id)
                const s = await this.secondaryRepo.createPerson(
                    createdAt,
                    properties,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    teamId,
                    isUserId,
                    isIdentified,
                    uuid,
                    distinctIds,
                    rightTx,
                    forcedId
                )
                if (!s.success) {
                    result = s
                    throw new Error('DualWrite abort: secondary creation conflict')
                }

                // Compare results between primary and secondary
                if (this.comparisonEnabled) {
                    this.compareCreatePersonResults(p, s)
                }

                result = p
                return true
            })
        } catch (err) {
            // if we captured a handled conflict from either side, surface it to match single-write behaviour
            if (result && !result.success && result.error === 'CreationConflict') {
                return result
            }
            throw err
        }
        return result
    }

    async updatePerson(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tag?: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        // Enforce version parity across primary/secondary: run primary first, then set secondary to primary's new version
        let primaryOut!: [InternalPerson, TopicMessage[], boolean]
        await this.coordinator.run(`updatePerson:${tag ?? 'update'}`, async (leftTx, rightTx) => {
            const p = await this.primaryRepo.updatePerson(person, { ...update }, tag, leftTx)
            primaryOut = p

            const primaryUpdated = p[0]
            const secondaryUpdate: Partial<InternalPerson> = {
                properties: primaryUpdated.properties,
                properties_last_updated_at: primaryUpdated.properties_last_updated_at,
                properties_last_operation: primaryUpdated.properties_last_operation,
                is_identified: primaryUpdated.is_identified,
                version: primaryUpdated.version,
            }

            const secondaryOut = await this.secondaryRepo.updatePerson(
                person,
                secondaryUpdate,
                tag ? `${tag}-secondary` : undefined,
                rightTx
            )

            // Compare results between primary and secondary
            if (this.comparisonEnabled) {
                this.compareUpdatePersonResults(primaryOut, secondaryOut, tag)
            }

            return true
        })
        return primaryOut
    }

    // No 2PC for this method, pretty sure its disabled in production
    async updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]> {
        let primaryOut!: [number | undefined, TopicMessage[]]
        await this.coordinator.run('updatePersonAssertVersion', async () => {
            const p = await this.primaryRepo.updatePersonAssertVersion({ ...personUpdate })
            primaryOut = p

            // Only perform secondary if the optimistic update succeeded on primary
            if (p[0] !== undefined) {
                const s = await this.secondaryRepo.updatePersonAssertVersion({ ...personUpdate })

                // Compare results
                if (this.comparisonEnabled) {
                    if (p[0] !== s[0]) {
                        dualWriteComparisonCounter.inc({
                            operation: 'updatePersonAssertVersion',
                            comparison_type: 'version_mismatch',
                            result: 'mismatch',
                        })
                    } else {
                        dualWriteComparisonCounter.inc({
                            operation: 'updatePersonAssertVersion',
                            comparison_type: 'version_match',
                            result: 'match',
                        })
                    }

                    // Compare message counts
                    this.compareTopicMessages('updatePersonAssertVersion', p[1], s[1])
                }
            }
            return true
        })
        return primaryOut
    }

    async deletePerson(person: InternalPerson): Promise<TopicMessage[]> {
        let messages!: TopicMessage[]
        await this.coordinator.run('deletePerson', async (lTx, rTx) => {
            const [p, s] = await Promise.all([
                this.primaryRepo.deletePerson(person, lTx),
                this.secondaryRepo.deletePerson(person, rTx),
            ])

            if (this.comparisonEnabled) {
                this.compareTopicMessages('deletePerson', p, s)
            }

            messages = p
            return true
        })
        return messages
    }

    async addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]> {
        let messages!: TopicMessage[]
        await this.coordinator.run('addDistinctId', async (lTx, rTx) => {
            const [p, s] = await Promise.all([
                this.primaryRepo.addDistinctId(person, distinctId, version, lTx),
                this.secondaryRepo.addDistinctId(person, distinctId, version, rTx),
            ])

            if (this.comparisonEnabled) {
                this.compareTopicMessages('addDistinctId', p, s)
            }

            messages = p
            return true
        })
        return messages
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        limit?: number
    ): Promise<MoveDistinctIdsResult> {
        let pResult!: MoveDistinctIdsResult
        await this.coordinator.run('moveDistinctIds', async (lTx, rTx) => {
            const [p, s] = await Promise.all([
                this.primaryRepo.moveDistinctIds(source, target, limit, lTx),
                this.secondaryRepo.moveDistinctIds(source, target, limit, rTx),
            ])
            // If both repositories return the same failure result, that's expected behavior
            // (e.g., both detected that the target person was deleted)
            if (!p.success && !s.success && p.error === s.error) {
                pResult = p
                // return false to rollback the transaction; the database failed anyhow so probably don't need to rollback
                return false
            }
            // If there's a mismatch in success or error type, that's unexpected
            if (p.success !== s.success || (!p.success && !s.success && p.error !== s.error)) {
                // Emit metric for mismatch
                if (this.comparisonEnabled) {
                    dualWriteComparisonCounter.inc({
                        operation: 'moveDistinctIds',
                        comparison_type: p.success !== s.success ? 'success_mismatch' : 'error_mismatch',
                        result: 'mismatch',
                    })
                }
                pResult = p
                // need to make sure we rollback this transaction
                return false
            }
            pResult = p
            return p.success
        })
        return pResult
    }

    async addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean> {
        let isMerged!: boolean
        await this.coordinator.run('addPersonlessDistinctId', async (lTx, rTx) => {
            const [p, s] = await Promise.all([
                this.primaryRepo.addPersonlessDistinctId(teamId, distinctId, lTx),
                this.secondaryRepo.addPersonlessDistinctId(teamId, distinctId, rTx),
            ])

            if (this.comparisonEnabled) {
                if (p !== s) {
                    dualWriteComparisonCounter.inc({
                        operation: 'addPersonlessDistinctId',
                        comparison_type: 'boolean_mismatch',
                        result: 'mismatch',
                    })
                } else {
                    dualWriteComparisonCounter.inc({
                        operation: 'addPersonlessDistinctId',
                        comparison_type: 'boolean_match',
                        result: 'match',
                    })
                }
            }

            isMerged = p
            return true
        })
        return isMerged
    }

    async fetchPersonDistinctIds(person: InternalPerson, limit?: number): Promise<string[]> {
        // This is a read operation, only use primary
        return await this.primaryRepo.fetchPersonDistinctIds(person, limit)
    }

    async addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean> {
        let isMerged!: boolean
        await this.coordinator.run('addPersonlessDistinctIdForMerge', async (lTx, rTx) => {
            const [p, s] = await Promise.all([
                this.primaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, lTx),
                this.secondaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, rTx),
            ])

            if (this.comparisonEnabled) {
                if (p !== s) {
                    dualWriteComparisonCounter.inc({
                        operation: 'addPersonlessDistinctIdForMerge',
                        comparison_type: 'boolean_mismatch',
                        result: 'mismatch',
                    })
                } else {
                    dualWriteComparisonCounter.inc({
                        operation: 'addPersonlessDistinctIdForMerge',
                        comparison_type: 'boolean_match',
                        result: 'match',
                    })
                }
            }

            isMerged = p
            return true
        })
        return isMerged
    }

    async personPropertiesSize(personId: string): Promise<number> {
        return await this.primaryRepo.personPropertiesSize(personId)
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id']
    ): Promise<void> {
        await this.coordinator.run('updateCohortsAndFeatureFlagsForMerge', async (lTx, rTx) => {
            await Promise.all([
                this.primaryRepo.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, lTx),
                this.secondaryRepo.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, rTx),
            ])
            return true
        })
    }
    async inTransaction<T>(
        description: string,
        transaction: (tx: PersonRepositoryTransaction) => Promise<T>
    ): Promise<T> {
        // Open a 2PC boundary spanning the entire callback.
        let result!: T
        try {
            await this.coordinator.run(`dual-tx:${description}`, async (lTx, rTx) => {
                const txWrapper = new DualWritePersonRepositoryTransaction(
                    this.primaryRepo,
                    this.secondaryRepo,
                    lTx,
                    rTx,
                    this.comparisonEnabled
                )
                result = await transaction(txWrapper)
                return true
            })
        } catch (err: any) {
            // Handle special cases where the transaction wrapper throws but we want to return a result
            // This matches the behavior of the direct createPerson method
            if (err.result && !err.result.success && err.result.error === 'CreationConflict') {
                return err.result as T
            }
            throw err
        }
        return result
    }

    private compareCreatePersonResults(primary: CreatePersonResult, secondary: CreatePersonResult): void {
        if (primary.success !== secondary.success) {
            dualWriteComparisonCounter.inc({
                operation: 'createPerson',
                comparison_type: 'success_mismatch',
                result: 'mismatch',
            })
            return
        }

        if (!primary.success || !secondary.success) {
            // Both failed, check if error types match
            if (!primary.success && !secondary.success && primary.error !== secondary.error) {
                dualWriteComparisonCounter.inc({
                    operation: 'createPerson',
                    comparison_type: 'error_mismatch',
                    result: 'mismatch',
                })
            } else {
                dualWriteComparisonCounter.inc({
                    operation: 'createPerson',
                    comparison_type: 'error_match',
                    result: 'match',
                })
            }
            return
        }

        // Both succeeded, compare person data
        const p = primary.person
        const s = secondary.person
        let hasMismatch = false

        if (JSON.stringify(p.properties) !== JSON.stringify(s.properties)) {
            dualWriteDataMismatchCounter.inc({ operation: 'createPerson', field: 'properties' })
            hasMismatch = true
        }
        if (p.version !== s.version) {
            dualWriteDataMismatchCounter.inc({ operation: 'createPerson', field: 'version' })
            hasMismatch = true
        }
        if (p.is_identified !== s.is_identified) {
            dualWriteDataMismatchCounter.inc({ operation: 'createPerson', field: 'is_identified' })
            hasMismatch = true
        }
        if (p.is_user_id !== s.is_user_id) {
            dualWriteDataMismatchCounter.inc({ operation: 'createPerson', field: 'is_user_id' })
            hasMismatch = true
        }

        dualWriteComparisonCounter.inc({
            operation: 'createPerson',
            comparison_type: 'data_comparison',
            result: hasMismatch ? 'mismatch' : 'match',
        })
    }

    private compareUpdatePersonResults(
        primary: [InternalPerson, TopicMessage[], boolean],
        secondary: [InternalPerson, TopicMessage[], boolean],
        tag?: string
    ): void {
        const [pPerson, pMessages, pChanged] = primary
        const [sPerson, sMessages, sChanged] = secondary
        let hasMismatch = false

        if (JSON.stringify(pPerson.properties) !== JSON.stringify(sPerson.properties)) {
            dualWriteDataMismatchCounter.inc({ operation: `updatePerson:${tag ?? 'update'}`, field: 'properties' })
            hasMismatch = true
        }
        if (pPerson.version !== sPerson.version) {
            dualWriteDataMismatchCounter.inc({ operation: `updatePerson:${tag ?? 'update'}`, field: 'version' })
            hasMismatch = true
        }
        if (pPerson.is_identified !== sPerson.is_identified) {
            dualWriteDataMismatchCounter.inc({ operation: `updatePerson:${tag ?? 'update'}`, field: 'is_identified' })
            hasMismatch = true
        }
        if (pChanged !== sChanged) {
            dualWriteDataMismatchCounter.inc({ operation: `updatePerson:${tag ?? 'update'}`, field: 'changed_flag' })
            hasMismatch = true
        }

        if (pMessages.length !== sMessages.length) {
            dualWriteDataMismatchCounter.inc({ operation: `updatePerson:${tag ?? 'update'}`, field: 'message_count' })
            hasMismatch = true
        }

        dualWriteComparisonCounter.inc({
            operation: `updatePerson:${tag ?? 'update'}`,
            comparison_type: 'data_comparison',
            result: hasMismatch ? 'mismatch' : 'match',
        })
    }

    private compareTopicMessages(operation: string, primary: TopicMessage[], secondary: TopicMessage[]): void {
        if (primary.length !== secondary.length) {
            dualWriteComparisonCounter.inc({
                operation,
                comparison_type: 'message_count_mismatch',
                result: 'mismatch',
            })
        } else {
            dualWriteComparisonCounter.inc({
                operation,
                comparison_type: 'message_count_match',
                result: 'match',
            })
        }
    }
}
