import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '../../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../../types'
import { CreatePersonResult, MoveDistinctIdsResult } from '../../../../utils/db/db'
import { TransactionClient } from '../../../../utils/db/postgres'
import { PersonRepositoryTransaction } from './person-repository-transaction'
import { RawPostgresPersonRepository } from './raw-postgres-person-repository'

export class PostgresPersonRepositoryTransaction implements PersonRepositoryTransaction {
    constructor(
        private transaction: TransactionClient,
        private repository: RawPostgresPersonRepository
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
        return await this.repository.createPerson(
            createdAt,
            properties,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            distinctIds,
            this.transaction
        )
    }

    async updatePerson(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tag?: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        return await this.repository.updatePerson(person, update, tag, this.transaction)
    }

    async deletePerson(person: InternalPerson): Promise<TopicMessage[]> {
        return await this.repository.deletePerson(person, this.transaction)
    }

    async addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]> {
        return await this.repository.addDistinctId(person, distinctId, version, this.transaction)
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        limit?: number
    ): Promise<MoveDistinctIdsResult> {
        return await this.repository.moveDistinctIds(source, target, limit, this.transaction)
    }

    async fetchPersonDistinctIds(person: InternalPerson, limit?: number): Promise<string[]> {
        return await this.repository.fetchPersonDistinctIds(person, limit, this.transaction)
    }

    async addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean> {
        return await this.repository.addPersonlessDistinctIdForMerge(teamId, distinctId, this.transaction)
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id']
    ): Promise<void> {
        return await this.repository.updateCohortsAndFeatureFlagsForMerge(
            teamID,
            sourcePersonID,
            targetPersonID,
            this.transaction
        )
    }
}
