import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { DB } from '../../../utils/db/db'
import { TransactionClient } from '../../../utils/db/postgres'
import { PersonsStoreForDistinctID } from './distinct-id-person-store'
import { PersonsStore } from './person-store'

export class MeasuringPersonsStoreForDistinctID implements PersonsStoreForDistinctID {
    constructor(private db: DB, private teamId: number, private distinctId: string) {}

    async fetchForChecking(): Promise<InternalPerson | null> {
        const person = await this.db.fetchPerson(this.teamId, this.distinctId, { useReadReplica: true })
        return person ?? null
    }

    async fetchForUpdate(): Promise<InternalPerson | null> {
        const person = await this.db.fetchPerson(this.teamId, this.distinctId)
        return person ?? null
    }

    async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        distinctIds?: { distinctId: string; version?: number }[],
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        return await this.db.createPerson(
            createdAt,
            properties,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            distinctIds,
            tx
        )
    }

    async updatePersonDeprecated(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        return await this.db.updatePersonDeprecated(person, update, tx)
    }

    async deletePerson(person: InternalPerson, tx?: TransactionClient): Promise<TopicMessage[]> {
        return await this.db.deletePerson(person, tx)
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        return await this.db.addDistinctId(person, distinctId, version, tx)
    }

    async addDistinctIdPooled(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        return await this.db.addDistinctIdPooled(person, distinctId, version, tx)
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        return await this.db.moveDistinctIds(source, target, tx)
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        tx?: TransactionClient
    ): Promise<void> {
        await this.db.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, tx)
    }

    async addPersonlessDistinctId(teamId: number, distinctId: string): Promise<boolean> {
        return await this.db.addPersonlessDistinctId(teamId, distinctId)
    }

    async addPersonlessDistinctIdForMerge(
        teamId: number,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<boolean> {
        return await this.db.addPersonlessDistinctIdForMerge(teamId, distinctId, tx)
    }
}

export class MeasuringPersonsStore implements PersonsStore {
    constructor(private db: DB) {}

    forDistinctID(teamId: number, distinctId: string): PersonsStoreForDistinctID {
        return new MeasuringPersonsStoreForDistinctID(this.db, teamId, distinctId)
    }

    async reportMetrics(): Promise<void> {
        // Will be implemented later
    }
}
