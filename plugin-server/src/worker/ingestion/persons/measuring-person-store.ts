import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { DB } from '../../../utils/db/db'
import { PostgresUse, TransactionClient } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { personMethodCallsPerBatchHistogram } from './metrics'
import { PersonsStore } from './persons-store'
import { PersonsStoreForBatch } from './persons-store-for-batch'
import { PersonsStoreForDistinctIdBatch } from './persons-store-for-distinct-id-batch'

type MethodName =
    | 'fetchForChecking'
    | 'fetchForUpdate'
    | 'createPerson'
    | 'updatePersonDeprecated'
    | 'deletePerson'
    | 'addDistinctId'
    | 'moveDistinctIds'
    | 'updateCohortsAndFeatureFlagsForMerge'
    | 'addPersonlessDistinctId'
    | 'addPersonlessDistinctIdForMerge'

const ALL_METHODS: MethodName[] = [
    'fetchForChecking',
    'fetchForUpdate',
    'createPerson',
    'updatePersonDeprecated',
    'deletePerson',
    'addDistinctId',
    'moveDistinctIds',
    'updateCohortsAndFeatureFlagsForMerge',
    'addPersonlessDistinctId',
    'addPersonlessDistinctIdForMerge',
]

export class MeasuringPersonsStore implements PersonsStore {
    constructor(private db: DB) {}

    forBatch(): PersonsStoreForBatch {
        return new MeasuringPersonsStoreForBatch(this.db)
    }
}

export class MeasuringPersonsStoreForBatch implements PersonsStoreForBatch {
    private distinctIdStores: Map<string, MeasuringPersonsStoreForDistinctIdBatch>

    constructor(private db: DB) {
        this.distinctIdStores = new Map()
    }

    forDistinctID(token: string, distinctId: string): PersonsStoreForDistinctIdBatch {
        const key = `${token}:${distinctId}`
        if (!this.distinctIdStores.has(key)) {
            this.distinctIdStores.set(key, new MeasuringPersonsStoreForDistinctIdBatch(this.db, token, distinctId))
        } else {
            logger.warn('⚠️', 'Reusing existing persons store for distinct ID in batch', { token, distinctId })
        }
        return this.distinctIdStores.get(key)!
    }

    reportBatch(): void {
        for (const store of this.distinctIdStores.values()) {
            const methodCounts = store.getMethodCounts()
            for (const [method, count] of methodCounts.entries()) {
                personMethodCallsPerBatchHistogram.observe({ method }, count)
            }
        }
    }
}

export class MeasuringPersonsStoreForDistinctIdBatch implements PersonsStoreForDistinctIdBatch {
    private methodCounts: Map<MethodName, number>
    private personCache: Map<string, InternalPerson | null>

    constructor(private db: DB, private token: string, private distinctId: string) {
        this.methodCounts = new Map()
        for (const method of ALL_METHODS) {
            this.methodCounts.set(method, 0)
        }
        this.personCache = new Map()
    }

    private getCacheKey(teamId: number, distinctId: string): string {
        return `${teamId}:${distinctId}`
    }

    private clearCache(): void {
        this.personCache.clear()
    }

    private getCachedPerson(teamId: number, distinctId: string): InternalPerson | null | undefined {
        const cacheKey = this.getCacheKey(teamId, distinctId)
        return this.personCache.get(cacheKey)
    }

    private setCachedPerson(teamId: number, distinctId: string, person: InternalPerson | null): void {
        const cacheKey = this.getCacheKey(teamId, distinctId)
        this.personCache.set(cacheKey, person)
    }

    async inTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T> {
        return await this.db.postgres.transaction(PostgresUse.COMMON_WRITE, description, transaction)
    }

    async fetchForChecking(teamId: Team['id'], distinctId: string): Promise<InternalPerson | null> {
        this.incrementCount('fetchForChecking')
        const cachedPerson = this.getCachedPerson(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson
        }

        const person = await this.db.fetchPerson(teamId, distinctId, { useReadReplica: true })
        return person ?? null
    }

    async fetchForUpdate(teamId: Team['id'], distinctId: string): Promise<InternalPerson | null> {
        this.incrementCount('fetchForUpdate')
        const cachedPerson = this.getCachedPerson(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson
        }

        const person = await this.db.fetchPerson(teamId, distinctId, { useReadReplica: false })
        this.setCachedPerson(teamId, distinctId, person ?? null)
        return person ?? null
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
        distinctIds?: { distinctId: string; version?: number }[],
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        this.incrementCount('createPerson')
        this.clearCache()
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
        this.incrementCount('updatePersonDeprecated')
        this.clearCache()
        return await this.db.updatePersonDeprecated(person, update, tx)
    }

    async deletePerson(person: InternalPerson, tx?: TransactionClient): Promise<TopicMessage[]> {
        this.incrementCount('deletePerson')
        this.clearCache()
        return await this.db.deletePerson(person, tx)
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        this.incrementCount('addDistinctId')
        this.clearCache()
        return await this.db.addDistinctId(person, distinctId, version, tx)
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        this.incrementCount('moveDistinctIds')
        this.clearCache()
        return await this.db.moveDistinctIds(source, target, tx)
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        tx?: TransactionClient
    ): Promise<void> {
        this.incrementCount('updateCohortsAndFeatureFlagsForMerge')
        this.clearCache()
        await this.db.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, tx)
    }

    async addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean> {
        this.incrementCount('addPersonlessDistinctId')
        this.clearCache()
        return await this.db.addPersonlessDistinctId(teamId, distinctId)
    }

    async addPersonlessDistinctIdForMerge(
        teamId: Team['id'],
        distinctId: string,
        tx?: TransactionClient
    ): Promise<boolean> {
        this.incrementCount('addPersonlessDistinctIdForMerge')
        this.clearCache()
        return await this.db.addPersonlessDistinctIdForMerge(teamId, distinctId, tx)
    }

    async personPropertiesSize(teamId: Team['id'], distinctId: string): Promise<number> {
        return await this.db.personPropertiesSize(teamId, distinctId)
    }

    getMethodCounts(): Map<MethodName, number> {
        return new Map(this.methodCounts)
    }

    private incrementCount(method: MethodName): void {
        this.methodCounts.set(method, (this.methodCounts.get(method) || 0) + 1)
    }
}
