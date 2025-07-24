import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { MoveDistinctIdsResult } from '../../../utils/db/db'
import { PersonRepositoryTransaction } from './person-repository-transaction'
import { PersonsStoreForBatch } from './persons-store-for-batch'

/**
 * PersonsStoreTransaction that delegates to a store with a transaction.
 * This can be used by any store that implements PersonsStoreForBatch.
 */
export class PersonsStoreTransaction {
    constructor(private store: PersonsStoreForBatch, private tx: PersonRepositoryTransaction) {}

    async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        distinctIds?: { distinctId: string; version?: number }[]
    ): Promise<[InternalPerson, TopicMessage[]]> {
        return await this.store.createPerson(
            createdAt,
            properties,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            distinctIds,
            this.tx
        )
    }

    async updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        return await this.store.updatePersonForMerge(person, update, distinctId, this.tx)
    }

    async updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        return await this.store.updatePersonWithPropertiesDiffForUpdate(
            person,
            propertiesToSet,
            propertiesToUnset,
            otherUpdates,
            distinctId,
            this.tx
        )
    }

    async deletePerson(person: InternalPerson, distinctId: string): Promise<TopicMessage[]> {
        return await this.store.deletePerson(person, distinctId, this.tx)
    }

    async addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]> {
        return await this.store.addDistinctId(person, distinctId, version, this.tx)
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string
    ): Promise<MoveDistinctIdsResult> {
        return await this.store.moveDistinctIds(source, target, distinctId, this.tx)
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string
    ): Promise<void> {
        return await this.store.updateCohortsAndFeatureFlagsForMerge(
            teamID,
            sourcePersonID,
            targetPersonID,
            distinctId,
            this.tx
        )
    }

    async addPersonlessDistinctIdForMerge(teamId: number, distinctId: string): Promise<boolean> {
        return await this.store.addPersonlessDistinctIdForMerge(teamId, distinctId, this.tx)
    }
}
