import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { DB } from '../../../utils/db/db'
import { PostgresUse, TransactionClient } from '../../../utils/db/postgres'
import {
    observeLatencyByVersion,
    personCacheOperationsCounter,
    personDatabaseOperationsPerBatchHistogram,
    personFetchForCheckingCacheOperationsCounter,
    personFetchForUpdateCacheOperationsCounter,
    personMethodCallsPerBatchHistogram,
    totalPersonUpdateLatencyPerBatchHistogram,
} from './metrics'
import { PersonsStore } from './persons-store'
import { PersonsStoreForBatch } from './persons-store-for-batch'

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

type UpdateType = 'forUpdate' | 'forMerge'

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
    private cacheMetrics: CacheMetrics
    private methodCountsPerDistinctId: Map<string, Map<MethodName, number>>
    private databaseOperationCountsPerDistinctId: Map<string, Map<MethodName, number>>
    private updateLatencyPerDistinctIdSeconds: Map<string, Map<UpdateType, number>>
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
    private fetchPromisesForChecking: Map<string, Promise<InternalPerson | null>>
    private fetchPromisesForUpdate: Map<string, Promise<InternalPerson | null>>

    constructor(
        private db: DB,
        private options: PersonsStoreOptions = {
            personCacheEnabledForUpdates: true,
            personCacheEnabledForChecks: true,
        }
    ) {
        this.methodCountsPerDistinctId = new Map()
        this.databaseOperationCountsPerDistinctId = new Map()
        this.updateLatencyPerDistinctIdSeconds = new Map()
        this.personCache = new Map()
        this.personCheckCache = new Map()
        this.fetchPromisesForChecking = new Map()
        this.fetchPromisesForUpdate = new Map()
        this.cacheMetrics = {
            updateCacheHits: 0,
            updateCacheMisses: 0,
            checkCacheHits: 0,
            checkCacheMisses: 0,
        }
    }

    flush(): Promise<void> {
        return Promise.resolve()
    }

    reportBatch(): void {
        for (const [_, methodCounts] of this.methodCountsPerDistinctId.entries()) {
            for (const [method, count] of methodCounts.entries()) {
                personMethodCallsPerBatchHistogram.observe({ method }, count)
            }
        }

        for (const [_, databaseOperationCounts] of this.databaseOperationCountsPerDistinctId.entries()) {
            for (const [operation, count] of databaseOperationCounts.entries()) {
                personDatabaseOperationsPerBatchHistogram.observe({ operation }, count)
            }
        }

        for (const [_, updateLatencyPerDistinctIdSeconds] of this.updateLatencyPerDistinctIdSeconds.entries()) {
            for (const [updateType, latency] of updateLatencyPerDistinctIdSeconds.entries()) {
                totalPersonUpdateLatencyPerBatchHistogram.observe({ update_type: updateType }, latency)
            }
        }

        personCacheOperationsCounter.inc({ cache: 'update', operation: 'hit' }, this.cacheMetrics.updateCacheHits)
        personCacheOperationsCounter.inc({ cache: 'update', operation: 'miss' }, this.cacheMetrics.updateCacheMisses)
        personCacheOperationsCounter.inc({ cache: 'check', operation: 'hit' }, this.cacheMetrics.checkCacheHits)
        personCacheOperationsCounter.inc({ cache: 'check', operation: 'miss' }, this.cacheMetrics.checkCacheMisses)
    }

    async inTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T> {
        return await this.db.postgres.transaction(PostgresUse.COMMON_WRITE, description, transaction)
    }

    async fetchForChecking(teamId: Team['id'], distinctId: string): Promise<InternalPerson | null> {
        this.incrementCount('fetchForChecking', distinctId)

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

        const cacheKey = this.getCacheKey(teamId, distinctId)
        let fetchPromise = this.fetchPromisesForChecking.get(cacheKey)
        if (!fetchPromise) {
            personFetchForCheckingCacheOperationsCounter.inc({ operation: 'miss' })
            fetchPromise = (async () => {
                try {
                    this.incrementDatabaseOperation('fetchForChecking', distinctId)
                    const start = performance.now()
                    const person = await this.db.fetchPerson(teamId, distinctId, { useReadReplica: true })
                    observeLatencyByVersion(person, start, 'fetchForChecking')
                    this.setCheckCachedPerson(teamId, distinctId, person ?? null)
                    return person ?? null
                } finally {
                    this.fetchPromisesForChecking.delete(cacheKey)
                }
            })()
            this.fetchPromisesForChecking.set(cacheKey, fetchPromise)
        } else {
            personFetchForCheckingCacheOperationsCounter.inc({ operation: 'hit' })
        }
        return fetchPromise
    }

    async fetchForUpdate(teamId: Team['id'], distinctId: string): Promise<InternalPerson | null> {
        this.incrementCount('fetchForUpdate', distinctId)

        const cachedPerson = this.getCachedPerson(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson
        }

        const cacheKey = this.getCacheKey(teamId, distinctId)
        let fetchPromise = this.fetchPromisesForUpdate.get(cacheKey)
        if (!fetchPromise) {
            personFetchForUpdateCacheOperationsCounter.inc({ operation: 'miss' })
            fetchPromise = (async () => {
                try {
                    this.incrementDatabaseOperation('fetchForUpdate', distinctId)
                    const start = performance.now()
                    const person = await this.db.fetchPerson(teamId, distinctId, { useReadReplica: false })
                    observeLatencyByVersion(person, start, 'fetchForUpdate')
                    this.setCachedPerson(teamId, distinctId, person ?? null)
                    return person ?? null
                } finally {
                    this.fetchPromisesForUpdate.delete(cacheKey)
                }
            })()
            this.fetchPromisesForUpdate.set(cacheKey, fetchPromise)
        } else {
            personFetchForUpdateCacheOperationsCounter.inc({ operation: 'hit' })
        }
        return fetchPromise
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
        this.incrementCount('createPerson', distinctIds?.[0].distinctId ?? '')
        this.clearCache()
        this.incrementDatabaseOperation('createPerson', distinctIds?.[0]?.distinctId ?? '')
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

    async updatePersonForUpdate(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        return this.updatePerson(person, update, tx, 'updatePersonForUpdate', 'forUpdate', distinctId)
    }

    async updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        return this.updatePerson(person, update, tx, 'updatePersonForMerge', 'forMerge', distinctId)
    }

    private async updatePerson(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tx: TransactionClient | undefined,
        methodName: MethodName,
        updateType: UpdateType,
        distinctId: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        this.incrementCount(methodName, distinctId)
        this.clearCache()
        this.incrementDatabaseOperation(methodName, distinctId)
        const start = performance.now()
        const response = await this.db.updatePerson(person, update, tx, updateType)
        this.recordUpdateLatency(updateType, (performance.now() - start) / 1000, distinctId)
        observeLatencyByVersion(person, start, methodName)
        return response
    }

    async deletePerson(person: InternalPerson, distinctId: string, tx?: TransactionClient): Promise<TopicMessage[]> {
        this.incrementCount('deletePerson', distinctId)
        this.clearCache()
        this.incrementDatabaseOperation('deletePerson', distinctId)
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
        this.incrementCount('addDistinctId', distinctId)
        this.clearCache()
        this.incrementDatabaseOperation('addDistinctId', distinctId)
        const start = performance.now()
        const response = await this.db.addDistinctId(person, distinctId, version, tx)
        observeLatencyByVersion(person, start, 'addDistinctId')
        return response
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        this.incrementCount('moveDistinctIds', distinctId)
        this.clearCache()
        this.incrementDatabaseOperation('moveDistinctIds', distinctId)
        const start = performance.now()
        const response = await this.db.moveDistinctIds(source, target, tx)
        observeLatencyByVersion(target, start, 'moveDistinctIds')
        return response
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string,
        tx?: TransactionClient
    ): Promise<void> {
        this.incrementCount('updateCohortsAndFeatureFlagsForMerge', distinctId)
        this.clearCache()
        await this.db.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, tx)
    }

    async addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean> {
        this.incrementCount('addPersonlessDistinctId', distinctId)
        this.clearCache()
        return await this.db.addPersonlessDistinctId(teamId, distinctId)
    }

    async addPersonlessDistinctIdForMerge(
        teamId: Team['id'],
        distinctId: string,
        tx?: TransactionClient
    ): Promise<boolean> {
        this.incrementCount('addPersonlessDistinctIdForMerge', distinctId)
        this.clearCache()
        return await this.db.addPersonlessDistinctIdForMerge(teamId, distinctId, tx)
    }

    async personPropertiesSize(teamId: Team['id'], distinctId: string): Promise<number> {
        return await this.db.personPropertiesSize(teamId, distinctId)
    }

    getMethodCountsPerDistinctId(): Map<string, Map<MethodName, number>> {
        return this.methodCountsPerDistinctId
    }

    getCacheMetrics(): CacheMetrics {
        return this.cacheMetrics
    }

    getDatabaseOperationCountsPerDistinctId(): Map<string, Map<MethodName, number>> {
        return this.databaseOperationCountsPerDistinctId
    }

    getUpdateLatencyPerDistinctIdSeconds(): Map<string, Map<UpdateType, number>> {
        return this.updateLatencyPerDistinctIdSeconds
    }

    // Private cache management methods

    private getCacheKey(teamId: number, distinctId: string): string {
        return `${teamId}:${distinctId}`
    }

    private clearCache(): void {
        this.personCache.clear()
        this.personCheckCache.clear()
        this.fetchPromisesForChecking.clear()
        this.fetchPromisesForUpdate.clear()
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

    private incrementCount(method: MethodName, distinctId: string): void {
        const methodCounts = this.methodCountsPerDistinctId.get(distinctId) || new Map()
        methodCounts.set(method, (methodCounts.get(method) || 0) + 1)
        this.methodCountsPerDistinctId.set(distinctId, methodCounts)
    }

    private incrementDatabaseOperation(operation: MethodName, distinctId: string): void {
        const databaseOperationCounts = this.databaseOperationCountsPerDistinctId.get(distinctId) || new Map()
        databaseOperationCounts.set(operation, (databaseOperationCounts.get(operation) || 0) + 1)
        this.databaseOperationCountsPerDistinctId.set(distinctId, databaseOperationCounts)
    }

    private recordUpdateLatency(updateType: UpdateType, latencySeconds: number, distinctId: string): void {
        const updateLatencyPerDistinctIdSeconds = this.updateLatencyPerDistinctIdSeconds.get(distinctId) || new Map()
        updateLatencyPerDistinctIdSeconds.set(
            updateType,
            (updateLatencyPerDistinctIdSeconds.get(updateType) || 0) + latencySeconds
        )
        this.updateLatencyPerDistinctIdSeconds.set(distinctId, updateLatencyPerDistinctIdSeconds)
    }
}
