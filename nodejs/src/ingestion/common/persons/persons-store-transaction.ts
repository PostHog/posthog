import { DateTime } from 'luxon'

import { PersonMessage } from '~/common/persons/person-message'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/common/utils/db/db'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'

import { PersonsStore } from './persons-store'

/**
 * PersonsStoreTransaction that delegates to a store with a transaction.
 * This can be used by any store that implements PersonsStore.
 */
export class PersonsStoreTransaction {
    constructor(
        private store: PersonsStore,
        private tx: PersonRepositoryTransaction
    ) {}

    async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds: { distinctId: string; version?: number }[] | undefined,
        batchId: number
    ): Promise<CreatePersonResult> {
        return await this.store.createPerson(
            createdAt,
            properties,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            primaryDistinctId,
            extraDistinctIds,
            this.tx,
            batchId
        )
    }

    async updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        batchId: number
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return await this.store.updatePersonForMerge(person, update, distinctId, batchId, this.tx)
    }

    async updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        batchId: number,
        forceUpdate?: boolean
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return await this.store.updatePersonWithPropertiesDiffForUpdate(
            person,
            propertiesToSet,
            propertiesToUnset,
            otherUpdates,
            distinctId,
            batchId,
            forceUpdate,
            this.tx
        )
    }

    async deletePerson(person: InternalPerson, distinctId: string): Promise<PersonMessage[]> {
        return await this.store.deletePerson(person, distinctId, this.tx)
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        batchId: number
    ): Promise<PersonMessage[]> {
        return await this.store.addDistinctId(person, distinctId, version, this.tx, batchId)
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        batchId: number
    ): Promise<MoveDistinctIdsResult> {
        return await this.store.moveDistinctIds(source, target, distinctId, limit, this.tx, batchId)
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

    async addPersonlessDistinctIdForMerge(teamId: number, distinctId: string, batchId: number): Promise<boolean> {
        return await this.store.addPersonlessDistinctIdForMerge(teamId, distinctId, this.tx, batchId)
    }

    async fetchPersonDistinctIds(person: InternalPerson, distinctId: string, limit?: number): Promise<string[]> {
        return await this.store.fetchPersonDistinctIds(person, distinctId, limit, this.tx)
    }
}
