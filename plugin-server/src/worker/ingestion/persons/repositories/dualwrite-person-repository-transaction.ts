import { DateTime } from 'luxon'
import { Properties } from '@posthog/plugin-scaffold'
import { TopicMessage } from '~/kafka/producer'
import {
    CreatePersonResult,
    MoveDistinctIdsResult,
} from '~/utils/db/db'
import { TransactionClient } from '~/utils/db/postgres'
import { logger } from '~/utils/logger'
import {
    InternalPerson,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
} from '~/types'
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
      const [p, s] = await Promise.all([
        this.primaryRepo.createPerson(
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
        ),
        this.secondaryRepo.createPerson(
          createdAt,
          properties,
          propertiesLastUpdatedAt,
          propertiesLastOperation,
          teamId,
          isUserId,
          isIdentified,
          uuid,
          distinctIds,
          this.rTx
        ),
      ])
      if (!p.success || !s.success) {
        throw new Error(`DualWrite TX createPerson mismatch: primary=${p.success}, secondary=${s.success}`)
      }
      return p
    }
  
    async updatePerson(
      person: InternalPerson,
      update: Partial<InternalPerson>,
      tag?: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
      const p = await this.primaryRepo.updatePerson(person, { ...update }, tag, this.lTx)
      await this.secondaryRepo.updatePerson(person, { ...update }, tag ? `${tag}-secondary` : undefined, this.rTx)
      return p
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
        throw new Error(`DualWrite TX moveDistinctIds mismatch: primary=${p.success}, secondary=${s.success}`)
      }
      return p
    }
  
    async addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean> {
      const [p, s] = await Promise.all([
        this.primaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, this.lTx),
        this.secondaryRepo.addPersonlessDistinctIdForMerge(teamId, distinctId, this.rTx),
      ])
      if (p !== s) {
        logger.warn('DualWrite TX addPersonlessDistinctIdForMerge mismatch', { primary: p, secondary: s })
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
  }