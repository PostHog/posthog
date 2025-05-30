import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { DB } from '../../../utils/db/db'
import { PostgresUse, TransactionClient } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import {
    observeLatencyByVersion,
    personCacheOperationsCounter,
    personDatabaseOperationsPerBatchHistogram,
    personMethodCallsPerBatchHistogram,
    totalPersonUpdateLatencyPerBatchHistogram,
} from './metrics'
import { PersonsStore } from './persons-store'
import { PersonsStoreForBatch } from './persons-store-for-batch'
import { PersonsStoreForDistinctIdBatch } from './persons-store-for-distinct-id-batch'

type MethodName =
    | 'fetchForChecking'
    | 'fetchForUpdate'
    | 'createPerson'
    | 'updatePersonForUpdate'
    | 'updatePersonForMerge'
    | 'deletePerson'
    | 'addDistinctId'
    | 'moveDistinctIds'
    | 'updateCohortsAndFeatureFlagsForMerge'
    | 'addPersonlessDistinctId'
    | 'addPersonlessDistinctIdForMerge'
    | 'updatePersonWithPropertiesDiffForUpdate'

const ALL_METHODS: MethodName[] = [
    'fetchForChecking',
    'fetchForUpdate',
    'createPerson',
    'updatePersonForUpdate',
    'updatePersonForMerge',
    'deletePerson',
    'addDistinctId',
    'moveDistinctIds',
    'updateCohortsAndFeatureFlagsForMerge',
    'addPersonlessDistinctId',
    'addPersonlessDistinctIdForMerge',
    'updatePersonWithPropertiesDiffForUpdate',
]

type UpdateType = 'forUpdate' | 'forMerge'

const ALL_UPDATE_TYPES: UpdateType[] = ['forUpdate', 'forMerge']

export interface PersonsStoreOptions {
    personCacheEnabledForUpdates: boolean
    personCacheEnabledForChecks: boolean
}

interface CacheMetrics {
    updateCacheHits: number
    updateCacheMisses: number
    checkCacheHits: number
    checkCacheMisses: number
}

export class MeasuringPersonsStore implements PersonsStore {
    constructor(private db: DB, private options: PersonsStoreOptions) {}

    forBatch(): PersonsStoreForBatch {
        return new MeasuringPersonsStoreForBatch(this.db, this.options)
    }
}

export class MeasuringPersonsStoreForBatch implements PersonsStoreForBatch {
    private distinctIdStores: Map<string, MeasuringPersonsStoreForDistinctIdBatch>

    constructor(private db: DB, private options: PersonsStoreOptions) {
        this.distinctIdStores = new Map()
    }

    forDistinctID(token: string, distinctId: string): PersonsStoreForDistinctIdBatch {
        const key = `${token}:${distinctId}`
        if (!this.distinctIdStores.has(key)) {
            this.distinctIdStores.set(
                key,
                new MeasuringPersonsStoreForDistinctIdBatch(this.db, token, distinctId, this.options)
            )
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

            const databaseCounts = store.getDatabaseOperationCounts()
            for (const [operation, count] of databaseCounts.entries()) {
                personDatabaseOperationsPerBatchHistogram.observe({ operation }, count)
            }

            const updateLatencyPerDistinctId = store.getUpdateLatencyPerDistinctIdSeconds()
            for (const [updateType, latency] of updateLatencyPerDistinctId.entries()) {
                totalPersonUpdateLatencyPerBatchHistogram.observe({ update_type: updateType }, latency)
            }

            const cacheMetrics = store.getCacheMetrics()
            personCacheOperationsCounter.inc({ cache: 'update', operation: 'hit' }, cacheMetrics.updateCacheHits)
            personCacheOperationsCounter.inc({ cache: 'update', operation: 'miss' }, cacheMetrics.updateCacheMisses)
            personCacheOperationsCounter.inc({ cache: 'check', operation: 'hit' }, cacheMetrics.checkCacheHits)
            personCacheOperationsCounter.inc({ cache: 'check', operation: 'miss' }, cacheMetrics.checkCacheMisses)
        }
    }
}

export class MeasuringPersonsStoreForDistinctIdBatch implements PersonsStoreForDistinctIdBatch {
    private methodCounts: Map<MethodName, number>
    private cacheMetrics: CacheMetrics
    private databaseOperationCounts: Map<MethodName, number>
    private updateLatencyPerDistinctIdSeconds: Map<UpdateType, number>
    /**
     * We maintain two separate person caches for different read patterns:
     *
     * personCache: Used by fetchForUpdate, contains data from the primary database.
     * Must be used when we need to modify person properties to avoid race conditions
     * with stale data. This is the source of truth for writes.
     *
     * personCheckCache: Used by fetchForChecking, contains data from read replicas.
     * Can be used for read-only operations but may return stale data. Should NOT be
     * used when we need to modify person properties as it could lead to race conditions
     * or lost updates.
     *
     * Both caches are cleared on any operation that modifies person data.
     */
    private personCache: Map<string, InternalPerson | null>
    private personCheckCache: Map<string, InternalPerson | null>

    constructor(
        private db: DB,
        private token: string,
        private distinctId: string,
        private options: PersonsStoreOptions = {
            personCacheEnabledForUpdates: true,
            personCacheEnabledForChecks: true,
        }
    ) {
        this.methodCounts = new Map()
        this.databaseOperationCounts = new Map()

        for (const method of ALL_METHODS) {
            this.methodCounts.set(method, 0)
            this.databaseOperationCounts.set(method, 0)
        }

        this.updateLatencyPerDistinctIdSeconds = new Map()
        for (const updateType of ALL_UPDATE_TYPES) {
            this.updateLatencyPerDistinctIdSeconds.set(updateType, 0)
        }

        this.personCache = new Map()
        this.personCheckCache = new Map()

        this.cacheMetrics = {
            updateCacheHits: 0,
            updateCacheMisses: 0,
            checkCacheHits: 0,
            checkCacheMisses: 0,
        }
    }

    // Public interface methods

    async inTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T> {
        return await this.db.postgres.transaction(PostgresUse.COMMON_WRITE, description, transaction)
    }

    async fetchForChecking(teamId: Team['id'], distinctId: string): Promise<InternalPerson | null> {
        this.incrementCount('fetchForChecking')

        // First check the main cache
        const cachedPerson = this.getCachedPerson(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson
        }

        // Then check the checking-specific cache
        const checkCachedPerson = this.getCheckCachedPerson(teamId, distinctId)
        if (checkCachedPerson !== undefined) {
            return checkCachedPerson
        }

        this.incrementDatabaseOperation('fetchForChecking')
        const start = performance.now()
        const person = await this.db.fetchPerson(teamId, distinctId, { useReadReplica: true })
        observeLatencyByVersion(person, start, 'fetchForChecking')
        this.setCheckCachedPerson(teamId, distinctId, person ?? null)
        return person ?? null
    }

    async fetchForUpdate(teamId: Team['id'], distinctId: string): Promise<InternalPerson | null> {
        this.incrementCount('fetchForUpdate')

        const cachedPerson = this.getCachedPerson(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson
        }

        this.incrementDatabaseOperation('fetchForUpdate')
        const start = performance.now()
        const person = await this.db.fetchPerson(teamId, distinctId, { useReadReplica: false })
        observeLatencyByVersion(person, start, 'fetchForUpdate')
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
        this.incrementDatabaseOperation('createPerson')
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

    async updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        return this.updatePersonWithPropertiesDiff(
            person,
            propertiesToSet,
            propertiesToUnset,
            otherUpdates,
            tx,
            'updatePersonWithPropertiesDiffForUpdate',
            'forUpdate'
        )
    }

    async updatePersonForUpdate(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        return this.updatePerson(person, update, tx, 'updatePersonForUpdate', 'forUpdate')
    }

    async updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        return this.updatePerson(person, update, tx, 'updatePersonForMerge', 'forMerge')
    }

    private async updatePersonWithPropertiesDiff(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        tx: TransactionClient | undefined,
        methodName: MethodName,
        updateType: UpdateType
    ): Promise<[InternalPerson, TopicMessage[]]> {
        this.incrementCount(methodName)
        this.clearCache()
        this.incrementDatabaseOperation(methodName)
        const start = performance.now()
        const response = await this.db.updatePersonWithMergeOperator(
            person,
            propertiesToSet,
            propertiesToUnset,
            otherUpdates,
            tx,
            updateType
        )
        this.recordUpdateLatency(updateType, (performance.now() - start) / 1000)
        observeLatencyByVersion(person, start, methodName)
        return response
    }

    private async updatePerson(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tx: TransactionClient | undefined,
        methodName: MethodName,
        updateType: UpdateType
    ): Promise<[InternalPerson, TopicMessage[]]> {
        this.incrementCount(methodName)
        this.clearCache()
        this.incrementDatabaseOperation(methodName)
        const start = performance.now()
        const response = await this.db.updatePersonDeprecated(person, update, tx, updateType)
        this.recordUpdateLatency(updateType, (performance.now() - start) / 1000)
        observeLatencyByVersion(person, start, methodName)
        return response
    }

    async deletePerson(person: InternalPerson, tx?: TransactionClient): Promise<TopicMessage[]> {
        this.incrementCount('deletePerson')
        this.clearCache()
        this.incrementDatabaseOperation('deletePerson')
        const start = performance.now()
        const response = await this.db.deletePerson(person, tx)
        observeLatencyByVersion(person, start, 'deletePerson')
        return response
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        this.incrementCount('addDistinctId')
        this.clearCache()
        this.incrementDatabaseOperation('addDistinctId')
        const start = performance.now()
        const response = await this.db.addDistinctId(person, distinctId, version, tx)
        observeLatencyByVersion(person, start, 'addDistinctId')
        return response
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        this.incrementCount('moveDistinctIds')
        this.clearCache()
        this.incrementDatabaseOperation('moveDistinctIds')
        const start = performance.now()
        const response = await this.db.moveDistinctIds(source, target, tx)
        observeLatencyByVersion(target, start, 'moveDistinctIds')
        return response
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

    getCacheMetrics(): CacheMetrics {
        return this.cacheMetrics
    }

    getDatabaseOperationCounts(): Map<string, number> {
        return new Map(this.databaseOperationCounts)
    }

    getUpdateLatencyPerDistinctIdSeconds(): Map<UpdateType, number> {
        return this.updateLatencyPerDistinctIdSeconds
    }

    // Private cache management methods

    private getCacheKey(teamId: number, distinctId: string): string {
        return `${teamId}:${distinctId}`
    }

    private clearCache(): void {
        this.personCache.clear()
        this.personCheckCache.clear()
    }

    private getCachedPerson(teamId: number, distinctId: string): InternalPerson | null | undefined {
        if (!this.options.personCacheEnabledForUpdates) {
            this.cacheMetrics.updateCacheMisses++
            return undefined
        }
        const cacheKey = this.getCacheKey(teamId, distinctId)
        const result = this.personCache.get(cacheKey)
        if (result !== undefined) {
            this.cacheMetrics.updateCacheHits++
        } else {
            this.cacheMetrics.updateCacheMisses++
        }
        return result
    }

    private getCheckCachedPerson(teamId: number, distinctId: string): InternalPerson | null | undefined {
        if (!this.options.personCacheEnabledForChecks) {
            this.cacheMetrics.checkCacheMisses++
            return undefined
        }
        const cacheKey = this.getCacheKey(teamId, distinctId)
        const result = this.personCheckCache.get(cacheKey)
        if (result !== undefined) {
            this.cacheMetrics.checkCacheHits++
        } else {
            this.cacheMetrics.checkCacheMisses++
        }
        return result
    }

    private setCachedPerson(teamId: number, distinctId: string, person: InternalPerson | null): void {
        if (!this.options.personCacheEnabledForUpdates) {
            return
        }
        const cacheKey = this.getCacheKey(teamId, distinctId)
        this.personCache.set(cacheKey, person)
    }

    private setCheckCachedPerson(teamId: number, distinctId: string, person: InternalPerson | null): void {
        if (!this.options.personCacheEnabledForChecks) {
            return
        }
        const cacheKey = this.getCacheKey(teamId, distinctId)
        this.personCheckCache.set(cacheKey, person)
    }

    // Private utility methods

    private incrementCount(method: MethodName): void {
        this.methodCounts.set(method, (this.methodCounts.get(method) || 0) + 1)
    }

    private incrementDatabaseOperation(operation: MethodName): void {
        this.databaseOperationCounts.set(operation, (this.databaseOperationCounts.get(operation) || 0) + 1)
    }

    private recordUpdateLatency(updateType: UpdateType, latencySeconds: number): void {
        this.updateLatencyPerDistinctIdSeconds.set(
            updateType,
            (this.updateLatencyPerDistinctIdSeconds.get(updateType) || 0) + latencySeconds
        )
    }
}
