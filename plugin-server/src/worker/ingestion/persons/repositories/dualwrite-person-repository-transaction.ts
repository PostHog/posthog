import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '~/kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/utils/db/db'
import { TransactionClient } from '~/utils/db/postgres'

import { dualWriteComparisonCounter, dualWriteDataMismatchCounter } from '../metrics'
import { PersonRepositoryTransaction } from './person-repository-transaction'
import { RawPostgresPersonRepository } from './raw-postgres-person-repository'

export class DualWritePersonRepositoryTransaction implements PersonRepositoryTransaction {
    constructor(
        private primaryRepo: RawPostgresPersonRepository,
        private secondaryRepo: RawPostgresPersonRepository,
        private lTx: TransactionClient,
        private rTx: TransactionClient,
        private comparisonEnabled: boolean = false
    ) {}

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
            this.lTx
        )
        if (!p.success) {
            // We need to throw to trigger rollback, but preserve the error type
            // so the outer repository can handle it appropriately
            const error = new Error(`DualWrite primary create failed`)
            ;(error as any).result = p
            throw error
        }
        // force same ID on secondary
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
            this.rTx,
            forcedId
        )
        if (!s.success) {
            const error = new Error(`DualWrite secondary create failed`)
            ;(error as any).result = s
            throw error
        }

        // Compare results between primary and secondary
        if (this.comparisonEnabled) {
            this.compareCreatePersonResults(p, s)
        }

        return p
    }

    async updatePerson(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tag?: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        // Enforce version parity across primary/secondary: run primary first, then set secondary to primary's new version
        const primaryOut = await this.primaryRepo.updatePerson(person, { ...update }, tag, this.lTx)
        const primaryUpdated = primaryOut[0]
        const secondaryOut = await this.secondaryRepo.updatePerson(
            person,
            { ...update, version: primaryUpdated.version },
            tag ? `${tag}-secondary` : undefined,
            this.rTx
        )

        if (this.comparisonEnabled) {
            this.compareUpdatePersonResults(primaryOut, secondaryOut, tag)
        }

        return primaryOut
    }

    async deletePerson(person: InternalPerson): Promise<TopicMessage[]> {
        const [p, s] = await Promise.all([
            this.primaryRepo.deletePerson(person, this.lTx),
            this.secondaryRepo.deletePerson(person, this.rTx),
        ])

        if (this.comparisonEnabled) {
            this.compareTopicMessages('deletePerson', p, s)
        }

        return p
    }

    async addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]> {
        const [p, s] = await Promise.all([
            this.primaryRepo.addDistinctId(person, distinctId, version, this.lTx),
            this.secondaryRepo.addDistinctId(person, distinctId, version, this.rTx),
        ])

        if (this.comparisonEnabled) {
            this.compareTopicMessages('addDistinctId', p, s)
        }

        return p
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        limit?: number
    ): Promise<MoveDistinctIdsResult> {
        const [p, s] = await Promise.all([
            this.primaryRepo.moveDistinctIds(source, target, limit, this.lTx),
            this.secondaryRepo.moveDistinctIds(source, target, limit, this.rTx),
        ])
        // Match the behavior of the direct repository call:
        // If both repositories return the same failure result, that's expected behavior
        if (!p.success && !s.success && p.error === s.error) {
            return p
        }
        if (p.success !== s.success || (!p.success && !s.success && p.error !== s.error)) {
            if (this.comparisonEnabled) {
                dualWriteComparisonCounter.inc({
                    operation: 'moveDistinctIds',
                    comparison_type: p.success !== s.success ? 'success_mismatch' : 'error_mismatch',
                    result: 'mismatch',
                })
            }
            // In the direct repository, this causes a rollback via returning false from coordinator
            // In transaction context, we should throw to trigger rollback
            const pError = !p.success ? p.error : 'none'
            const sError = !s.success ? s.error : 'none'
            throw new Error(
                `DualWrite moveDistinctIds mismatch: primary=${p.success}/${pError}, secondary=${s.success}/${sError}`
            )
        }

        if (this.comparisonEnabled && p.success && s.success) {
            this.compareTopicMessages('moveDistinctIds', p.messages || [], s.messages || [])
        }

        return p
    }

    async fetchPersonDistinctIds(person: InternalPerson, limit?: number): Promise<string[]> {
        // This is a read operation, only use primary
        return await this.primaryRepo.fetchPersonDistinctIds(person, limit, this.lTx)
    }

    async addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean> {
        const [p, s] = await Promise.all([
            this.primaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, this.lTx),
            this.secondaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, this.rTx),
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

        return p
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id']
    ): Promise<void> {
        await Promise.all([
            this.primaryRepo.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, this.lTx),
            this.secondaryRepo.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, this.rTx),
        ])
    }

    private compareCreatePersonResults(primary: CreatePersonResult, secondary: CreatePersonResult): void {
        if (primary.success !== secondary.success) {
            dualWriteComparisonCounter.inc({
                operation: 'createPerson_tx',
                comparison_type: 'success_mismatch',
                result: 'mismatch',
            })
            return
        }

        if (!primary.success || !secondary.success) {
            if (!primary.success && !secondary.success && primary.error !== secondary.error) {
                dualWriteComparisonCounter.inc({
                    operation: 'createPerson_tx',
                    comparison_type: 'error_mismatch',
                    result: 'mismatch',
                })
            } else {
                dualWriteComparisonCounter.inc({
                    operation: 'createPerson_tx',
                    comparison_type: 'error_match',
                    result: 'match',
                })
            }
            return
        }

        const p = primary.person
        const s = secondary.person
        let hasMismatch = false

        if (JSON.stringify(p.properties) !== JSON.stringify(s.properties)) {
            dualWriteDataMismatchCounter.inc({ operation: 'createPerson_tx', field: 'properties' })
            hasMismatch = true
        }
        if (p.version !== s.version) {
            dualWriteDataMismatchCounter.inc({ operation: 'createPerson_tx', field: 'version' })
            hasMismatch = true
        }
        if (p.is_identified !== s.is_identified) {
            dualWriteDataMismatchCounter.inc({ operation: 'createPerson_tx', field: 'is_identified' })
            hasMismatch = true
        }
        if (p.is_user_id !== s.is_user_id) {
            dualWriteDataMismatchCounter.inc({ operation: 'createPerson_tx', field: 'is_user_id' })
            hasMismatch = true
        }

        dualWriteComparisonCounter.inc({
            operation: 'createPerson_tx',
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
            dualWriteDataMismatchCounter.inc({ operation: `updatePerson_tx:${tag ?? 'update'}`, field: 'properties' })
            hasMismatch = true
        }
        if (pPerson.version !== sPerson.version) {
            dualWriteDataMismatchCounter.inc({ operation: `updatePerson_tx:${tag ?? 'update'}`, field: 'version' })
            hasMismatch = true
        }
        if (pPerson.is_identified !== sPerson.is_identified) {
            dualWriteDataMismatchCounter.inc({
                operation: `updatePerson_tx:${tag ?? 'update'}`,
                field: 'is_identified',
            })
            hasMismatch = true
        }
        if (pChanged !== sChanged) {
            dualWriteDataMismatchCounter.inc({ operation: `updatePerson_tx:${tag ?? 'update'}`, field: 'changed_flag' })
            hasMismatch = true
        }

        if (pMessages.length !== sMessages.length) {
            dualWriteDataMismatchCounter.inc({
                operation: `updatePerson_tx:${tag ?? 'update'}`,
                field: 'message_count',
            })
            hasMismatch = true
        }

        dualWriteComparisonCounter.inc({
            operation: `updatePerson_tx:${tag ?? 'update'}`,
            comparison_type: 'data_comparison',
            result: hasMismatch ? 'mismatch' : 'match',
        })
    }

    private compareTopicMessages(operation: string, primary: TopicMessage[], secondary: TopicMessage[]): void {
        if (primary.length !== secondary.length) {
            dualWriteComparisonCounter.inc({
                operation: `${operation}_tx`,
                comparison_type: 'message_count_mismatch',
                result: 'mismatch',
            })
        } else {
            dualWriteComparisonCounter.inc({
                operation: `${operation}_tx`,
                comparison_type: 'message_count_match',
                result: 'match',
            })
        }
    }
}
