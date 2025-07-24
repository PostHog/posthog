import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { MoveDistinctIdsResult } from '../../../utils/db/db'
import { TransactionClient } from '../../../utils/db/postgres'
import { PersonRepositoryTransaction } from './person-repository-transaction'
import { PersonUpdate } from './person-update-batch'
import { RawPersonRepository } from './raw-person-repository'

export class BasePersonRepositoryTransaction implements PersonRepositoryTransaction {
    constructor(private transaction: TransactionClient, private repository: RawPersonRepository) {}

    async fetchPerson(
        teamId: Team['id'],
        distinctId: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<InternalPerson | undefined> {
        return await this.repository.fetchPerson(teamId, distinctId, options)
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
    ): Promise<[InternalPerson, TopicMessage[]]> {
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

    async updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]> {
        return await this.repository.updatePersonAssertVersion(personUpdate)
    }

    async deletePerson(person: InternalPerson): Promise<TopicMessage[]> {
        return await this.repository.deletePerson(person, this.transaction)
    }

    async addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]> {
        return await this.repository.addDistinctId(person, distinctId, version, this.transaction)
    }

    async moveDistinctIds(source: InternalPerson, target: InternalPerson): Promise<MoveDistinctIdsResult> {
        return await this.repository.moveDistinctIds(source, target, this.transaction)
    }

    async addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean> {
        return await this.repository.addPersonlessDistinctId(teamId, distinctId)
    }

    async addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean> {
        return await this.repository.addPersonlessDistinctIdForMerge(teamId, distinctId, this.transaction)
    }

    async personPropertiesSize(teamId: Team['id'], distinctId: string): Promise<number> {
        return await this.repository.personPropertiesSize(teamId, distinctId)
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
