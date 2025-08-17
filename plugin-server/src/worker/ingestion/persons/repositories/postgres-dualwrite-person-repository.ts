import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../../types'
import { CreatePersonResult, MoveDistinctIdsResult } from '../../../../utils/db/db'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { TwoPhaseCommitCoordinator } from '../../../../utils/db/two-phase'
import { logger as _logger } from '../../../../utils/logger'
import { PersonUpdate } from '../person-update-batch'
import { DualWritePersonRepositoryTransaction } from './dualwrite-person-repository-transaction'
import { PersonRepository } from './person-repository'
import { PersonRepositoryTransaction } from './person-repository-transaction'
import { PostgresPersonRepository } from './postgres-person-repository'
import type { PostgresPersonRepositoryOptions } from './postgres-person-repository'
import { RawPostgresPersonRepository } from './raw-postgres-person-repository'

export class PostgresDualWritePersonRepository implements PersonRepository {
    private coordinator: TwoPhaseCommitCoordinator
    private primaryRepo: RawPostgresPersonRepository
    private secondaryRepo: RawPostgresPersonRepository

    constructor(
        primaryRouter: PostgresRouter,
        secondaryRouter: PostgresRouter,
        options?: Partial<PostgresPersonRepositoryOptions>
    ) {
        this.primaryRepo = new PostgresPersonRepository(primaryRouter, options)
        this.secondaryRepo = new PostgresPersonRepository(secondaryRouter, options)
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
                // NICKS TODO: do we want any metrics/logs/observability here?
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
                // Mirror authoritative fields from the result of the primary update to guarantee parity
                properties: primaryUpdated.properties,
                properties_last_updated_at: primaryUpdated.properties_last_updated_at,
                properties_last_operation: primaryUpdated.properties_last_operation,
                is_identified: primaryUpdated.is_identified,
                version: primaryUpdated.version,
            }

            await this.secondaryRepo.updatePerson(
                person,
                secondaryUpdate,
                tag ? `${tag}-secondary` : undefined,
                rightTx
            )
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
        let isMerged!: boolean
        await this.coordinator.run('addPersonlessDistinctIds', async (lTx, rTx) => {
            const [p, _s] = await Promise.all([
                this.primaryRepo.addPersonlessDistinctId(teamId, distinctId, lTx),
                this.secondaryRepo.addPersonlessDistinctId(teamId, distinctId, rTx),
            ])
            isMerged = p
        })
        return isMerged
    }

    async addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean> {
        let isMerged!: boolean
        await this.coordinator.run('addPersonlessDistinctIdForMerge', async (lTx, rTx) => {
            const [p, _s] = await Promise.all([
                this.primaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, lTx),
                this.secondaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, rTx),
            ])
            isMerged = p
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
        await this.coordinator.run(`dual-tx:${description}`, async (lTx, rTx) => {
            const txWrapper = new DualWritePersonRepositoryTransaction(this.primaryRepo, this.secondaryRepo, lTx, rTx)
            result = await transaction(txWrapper)
            return true
        })
        return result
    }
}
