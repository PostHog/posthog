import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '~/kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/utils/db/db'
import { TransactionClient } from '~/utils/db/postgres'

import { PersonRepositoryTransaction } from './person-repository-transaction'
import { RawPostgresPersonRepository } from './raw-postgres-person-repository'

export class DualWritePersonRepositoryTransaction implements PersonRepositoryTransaction {
    constructor(
        private primaryRepo: RawPostgresPersonRepository,
        private secondaryRepo: RawPostgresPersonRepository,
        private lTx: TransactionClient,
        private rTx: TransactionClient
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
        await this.secondaryRepo.updatePerson(
            person,
            { ...update, version: primaryUpdated.version },
            tag ? `${tag}-secondary` : undefined,
            this.rTx
        )
        return primaryOut
    }

    async deletePerson(person: InternalPerson): Promise<TopicMessage[]> {
        const [p] = await Promise.all([
            this.primaryRepo.deletePerson(person, this.lTx),
            this.secondaryRepo.deletePerson(person, this.rTx),
        ])
        return p
    }

    async addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]> {
        const [p] = await Promise.all([
            this.primaryRepo.addDistinctId(person, distinctId, version, this.lTx),
            this.secondaryRepo.addDistinctId(person, distinctId, version, this.rTx),
        ])
        return p
    }

    async moveDistinctIds(source: InternalPerson, target: InternalPerson): Promise<MoveDistinctIdsResult> {
        const [p, s] = await Promise.all([
            this.primaryRepo.moveDistinctIds(source, target, this.lTx),
            this.secondaryRepo.moveDistinctIds(source, target, this.rTx),
        ])
        // Match the behavior of the direct repository call:
        // If both repositories return the same failure result, that's expected behavior
        if (!p.success && !s.success && p.error === s.error) {
            return p
        }
        // If there's a mismatch in success or error type, still return primary result
        // but the transaction coordinator will handle the rollback
        if (p.success !== s.success || (!p.success && !s.success && p.error !== s.error)) {
            // In the direct repository, this causes a rollback via returning false from coordinator
            // In transaction context, we should throw to trigger rollback
            const pError = !p.success ? p.error : 'none'
            const sError = !s.success ? s.error : 'none'
            throw new Error(
                `DualWrite moveDistinctIds mismatch: primary=${p.success}/${pError}, secondary=${s.success}/${sError}`
            )
        }
        return p
    }

    async addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean> {
        const [p, _s] = await Promise.all([
            this.primaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, this.lTx),
            this.secondaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, this.rTx),
        ])
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
}
