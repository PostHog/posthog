import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../../types'
import { CreatePersonResult, MoveDistinctIdsResult } from '../../../../utils/db/db'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { TwoPhaseCommitCoordinator } from '../../../../utils/db/two-phase'
import { logger } from '../../../../utils/logger'
import { PersonUpdate } from '../person-update-batch'
import { DualWritePersonRepositoryTransaction } from './dualwrite-person-repository-transaction'
import { PersonRepository } from './person-repository'
import { PersonRepositoryTransaction } from './person-repository-transaction'
import { PostgresPersonRepository } from './postgres-person-repository'
import { RawPostgresPersonRepository } from './raw-postgres-person-repository'

export class PostgresDualWritePersonRepository implements PersonRepository {
    private coordinator: TwoPhaseCommitCoordinator
    private primaryRepo: RawPostgresPersonRepository
    private secondaryRepo: RawPostgresPersonRepository

    constructor(primaryRouter: PostgresRouter, secondaryRouter: PostgresRouter) {
        this.primaryRepo = new PostgresPersonRepository(primaryRouter)
        this.secondaryRepo = new PostgresPersonRepository(secondaryRouter)
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
        let primaryResult!: CreatePersonResult
        await this.coordinator.run('createPerson', async (leftTx, rightTx) => {
            // serial: create on primary first
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
                throw new Error(`DualWrite primary create failed`)
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
                throw new Error(`DualWrite secondary create failed`)
            }

            primaryResult = p
            return true
        })
        return primaryResult
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
            await this.secondaryRepo.updatePerson(
                person,
                { ...update, version: primaryUpdated.version },
                tag ? `${tag}-secondary` : undefined,
                rightTx
            )
            return true
        })
        return primaryOut
    }

    // currently doesn't use txs from the coordinator because the updatePersonAssertVersion
    // is not transactional.
    // if we want to support this method, we'll have to address this
    async updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]> {
        let primaryOut!: [number | undefined, TopicMessage[]]
        await this.coordinator.run('updatePersonAssertVersion', async () => {
            const p = await this.primaryRepo.updatePersonAssertVersion({ ...personUpdate })
            primaryOut = p

            // Only perform secondary if the optimistic update succeeded on primary
            if (p[0] !== undefined) {
                await this.secondaryRepo.updatePersonAssertVersion({ ...personUpdate })
            }
            return true
        })
        return primaryOut
    }

    async deletePerson(person: InternalPerson): Promise<TopicMessage[]> {
        let messages!: TopicMessage[]
        await this.coordinator.run('deletePerson', async (lTx, rTx) => {
            const [p] = await Promise.all([
                this.primaryRepo.deletePerson(person, lTx),
                this.secondaryRepo.deletePerson(person, rTx),
            ])
            messages = p
            return true
        })
        return messages
    }

    async addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]> {
        let messages!: TopicMessage[]
        await this.coordinator.run('addDistinctId', async (lTx, rTx) => {
            const [p] = await Promise.all([
                this.primaryRepo.addDistinctId(person, distinctId, version, lTx),
                this.secondaryRepo.addDistinctId(person, distinctId, version, rTx),
            ])
            messages = p
            return true
        })
        return messages
    }

    async moveDistinctIds(source: InternalPerson, target: InternalPerson): Promise<MoveDistinctIdsResult> {
        let primary!: MoveDistinctIdsResult
        await this.coordinator.run('moveDistinctIds', async (lTx, rTx) => {
            const [p, s] = await Promise.all([
                this.primaryRepo.moveDistinctIds(source, target, lTx),
                this.secondaryRepo.moveDistinctIds(source, target, rTx),
            ])
            if (!p.success || !s.success) {
                throw new Error(`DualWrite moveDistinctIds mismatch: primary=${p.success}, secondary=${s.success}`)
            }
            primary = p
            return true
        })
        return primary
    }

    async addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean> {
        // One-off non-transactional write; still do both but no 2PC wrapper.
        // If you need strict guarantees here too, wrap in coordinator like others.
        const [p, s] = await Promise.all([
            this.primaryRepo.addPersonlessDistinctId(teamId, distinctId),
            this.secondaryRepo.addPersonlessDistinctId(teamId, distinctId),
        ])
        if (p !== s) {
            logger.warn('DualWrite addPersonlessDistinctId mismatch', { primary: p, secondary: s })
        }
        return p
    }

    async addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean> {
        let inserted!: boolean
        await this.coordinator.run('addPersonlessDistinctIdForMerge', async (lTx, rTx) => {
            const [p, s] = await Promise.all([
                this.primaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, lTx),
                this.secondaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, rTx),
            ])
            if (p !== s) {
                // mismatch is not fatal, but log and keep primary
                logger.warn('DualWrite addPersonlessDistinctIdForMerge mismatch', { primary: p, secondary: s })
            }
            inserted = p
            return true
        })
        return inserted
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
        await this.coordinator.run(`dual-tx:${description}`, async (lTx, rTx) => {
            const txWrapper = new DualWritePersonRepositoryTransaction(this.primaryRepo, this.secondaryRepo, lTx, rTx)
            result = await transaction(txWrapper)
            return true
        })
        return result
    }
}
