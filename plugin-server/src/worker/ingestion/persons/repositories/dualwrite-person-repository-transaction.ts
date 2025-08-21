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
            throw new Error(`DualWrite primary create failed`)
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
            throw new Error(`DualWrite secondary create failed`)
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
        if (!p.success || !s.success) {
            throw new Error(`DualWrite moveDistinctIds mismatch: primary=${p.success}, secondary=${s.success}`)
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
