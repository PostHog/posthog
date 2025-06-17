import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import pLimit from 'p-limit'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { DB } from '../../../utils/db/db'
import { MessageSizeTooLarge } from '../../../utils/db/error'
import { PostgresUse, TransactionClient } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { promiseRetry } from '../../../utils/retries'
import { BatchWritingStore } from '../stores/batch-writing-store'
import { captureIngestionWarning } from '../utils'
import {
    observeLatencyByVersion,
    personCacheOperationsCounter,
    personDatabaseOperationsPerBatchHistogram,
    personFetchForCheckingCacheOperationsCounter,
    personFetchForUpdateCacheOperationsCounter,
    personMethodCallsPerBatchHistogram,
    personOptimisticUpdateConflictsPerBatchCounter,
    totalPersonUpdateLatencyPerBatchHistogram,
} from './metrics'
import { fromInternalPerson, PersonUpdate, toInternalPerson } from './person-update-batch'
import { PersonsStore } from './persons-store'
import { PersonsStoreForBatch } from './persons-store-for-batch'

type MethodName =
    | 'fetchForChecking'
    | 'fetchForUpdate'
    | 'fetchPerson'
    | 'updatePersonOptimistically'
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
    | 'addPersonUpdateToBatch'

type UpdateType = 'updatePersonOptimistically' | 'updatePersonWithTransaction'

export interface BatchWritingPersonsStoreOptions {
    maxConcurrentUpdates: number
    optimisticUpdatesEnabled: boolean
    maxOptimisticUpdateRetries: number
    optimisticUpdateRetryInterval: number
}

const DEFAULT_OPTIONS: BatchWritingPersonsStoreOptions = {
    optimisticUpdatesEnabled: false,
    maxConcurrentUpdates: 10,
    maxOptimisticUpdateRetries: 5,
    optimisticUpdateRetryInterval: 50,
}

interface CacheMetrics {
    updateCacheHits: number
    updateCacheMisses: number
    checkCacheHits: number
    checkCacheMisses: number
}

export class BatchWritingPersonsStore implements PersonsStore {
    private options: BatchWritingPersonsStoreOptions

    constructor(private db: DB, options?: Partial<BatchWritingPersonsStoreOptions>) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
    }

    forBatch(): PersonsStoreForBatch {
        return new BatchWritingPersonsStoreForBatch(this.db, this.options)
    }
}

/**
 * This class is used to write persons to the database in batches.
 * It will use a cache to avoid reading the same person from the database multiple times.
 * And will accumulate all changes for the same person in a single batch. At the
 * end of the batch processing, it flushes all changes to the database.
 */
export class BatchWritingPersonsStoreForBatch implements PersonsStoreForBatch, BatchWritingStore {
    private personCheckCache: Map<string, InternalPerson | null>
    private personUpdateCache: Map<string, PersonUpdate | null>
    private fetchPromisesForUpdate: Map<string, Promise<InternalPerson | null>>
    private fetchPromisesForChecking: Map<string, Promise<InternalPerson | null>>
    private methodCountsPerDistinctId: Map<string, Map<MethodName, number>>
    private databaseOperationCountsPerDistinctId: Map<string, Map<MethodName, number>>
    private updateLatencyPerDistinctIdSeconds: Map<string, Map<UpdateType, number>>
    private cacheMetrics: CacheMetrics
    private options: BatchWritingPersonsStoreOptions

    constructor(private db: DB, options?: Partial<BatchWritingPersonsStoreOptions>) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
        this.personUpdateCache = new Map()
        this.personCheckCache = new Map()
        this.fetchPromisesForUpdate = new Map()
        this.fetchPromisesForChecking = new Map()
        this.methodCountsPerDistinctId = new Map()
        this.databaseOperationCountsPerDistinctId = new Map()
        this.updateLatencyPerDistinctIdSeconds = new Map()
        this.cacheMetrics = {
            updateCacheHits: 0,
            updateCacheMisses: 0,
            checkCacheHits: 0,
            checkCacheMisses: 0,
        }
    }

    async flush(): Promise<void> {
        const limit = pLimit(this.options.maxConcurrentUpdates)

        await Promise.all(
            Array.from(this.personUpdateCache.entries())
                .filter((entry): entry is [string, PersonUpdate] => {
                    const [_, update] = entry
                    return update !== null && update.needs_write
                })
                .map(([cacheKey, update]) =>
                    limit(async () => {
                        try {
                            if (this.options.optimisticUpdatesEnabled) {
                                await promiseRetry(
                                    () => this.updatePersonOptimistically(update),
                                    'updatePersonOptimistically',
                                    this.options.maxOptimisticUpdateRetries,
                                    this.options.optimisticUpdateRetryInterval,
                                    undefined,
                                    [MessageSizeTooLarge]
                                )
                            } else {
                                await promiseRetry(
                                    () => this.updatePersonWithTransaction(update, 'batch'),
                                    'updatePersonWithTransaction',
                                    this.options.maxOptimisticUpdateRetries,
                                    this.options.optimisticUpdateRetryInterval,
                                    undefined,
                                    [MessageSizeTooLarge]
                                )
                            }
                        } catch (error) {
                            // If the Kafka message is too large, we can't retry, so we need to capture a warning and stop retrying
                            if (error instanceof MessageSizeTooLarge) {
                                await captureIngestionWarning(
                                    this.db.kafkaProducer,
                                    update.team_id,
                                    'person_upsert_message_size_too_large',
                                    {
                                        personUuid: update.uuid,
                                        distinctId: update.distinct_id,
                                    }
                                )
                                return
                            }
                            logger.warn('⚠️', 'Falling back to direct update after max retries', {
                                teamId: update.team_id,
                                personUuid: update.uuid,
                                distinctId: update.distinct_id,
                            })
                            // Remove the person from the cache, so we don't try to update it again
                            this.personUpdateCache.delete(cacheKey)
                            await this.updatePersonWithTransaction(update, 'conflictRetry')
                        }
                    }).catch((error) => {
                        logger.error('Failed to update person after max retries and direct update fallback', {
                            error,
                            cacheKey,
                            teamId: update.team_id,
                            personUuid: update.uuid,
                            distinctId: update.distinct_id,
                            errorMessage: error instanceof Error ? error.message : String(error),
                            errorStack: error instanceof Error ? error.stack : undefined,
                        })
                        throw error
                    })
                )
        ).catch((error) => {
            logger.error('Failed to flush person updates', {
                error,
                errorMessage: error instanceof Error ? error.message : String(error),
                errorStack: error instanceof Error ? error.stack : undefined,
            })
            throw error
        })
    }

    async inTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T> {
        return await this.db.postgres.transaction(PostgresUse.COMMON_WRITE, description, transaction)
    }

    async fetchForChecking(teamId: Team['id'], distinctId: string): Promise<InternalPerson | null> {
        this.incrementCount('fetchForChecking', distinctId)

        // First check the main cache
        const cachedPerson = this.getCachedPersonForUpdate(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson === null ? null : toInternalPerson(cachedPerson)
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

        const cachedPerson = this.getCachedPersonForUpdate(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson === null ? null : toInternalPerson(cachedPerson)
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
                    if (person !== undefined) {
                        const personUpdate = fromInternalPerson(person, distinctId)
                        this.setCachedPersonForUpdate(teamId, distinctId, personUpdate)
                        return person
                    } else {
                        this.setCachedPersonForUpdate(teamId, distinctId, null)
                        return null
                    }
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

    updatePersonForUpdate(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        _tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        this.incrementCount('updatePersonForUpdate', distinctId)
        return Promise.resolve(this.addPersonUpdateToBatch(person, update, distinctId))
    }

    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        _tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        this.incrementCount('updatePersonForMerge', distinctId)
        return Promise.resolve(this.addPersonUpdateToBatch(person, update, distinctId))
    }

    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        _tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        return Promise.resolve(
            this.addPersonPropertiesUpdateToBatch(person, propertiesToSet, propertiesToUnset, otherUpdates, distinctId)
        )
    }

    async deletePerson(person: InternalPerson, distinctId: string, tx?: TransactionClient): Promise<TopicMessage[]> {
        this.incrementCount('deletePerson', distinctId)
        this.incrementDatabaseOperation('deletePerson', distinctId)
        const start = performance.now()
        const response = await this.db.deletePerson(person, tx)
        observeLatencyByVersion(person, start, 'deletePerson')
        // Clear cache for the person
        this.clearCache(person.team_id, distinctId)
        return response
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        this.incrementCount('addDistinctId', distinctId)
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
        await this.db.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, tx)
    }

    async addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean> {
        this.incrementCount('addPersonlessDistinctId', distinctId)
        return await this.db.addPersonlessDistinctId(teamId, distinctId)
    }

    async addPersonlessDistinctIdForMerge(
        teamId: Team['id'],
        distinctId: string,
        tx?: TransactionClient
    ): Promise<boolean> {
        this.incrementCount('addPersonlessDistinctIdForMerge', distinctId)
        return await this.db.addPersonlessDistinctIdForMerge(teamId, distinctId, tx)
    }

    async personPropertiesSize(teamId: Team['id'], distinctId: string): Promise<number> {
        return await this.db.personPropertiesSize(teamId, distinctId)
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

    // Private implementation methods

    private getCacheKey(teamId: number, distinctId: string): string {
        return `${teamId}:${distinctId}`
    }

    private clearCache(teamId: number, distinctId: string): void {
        const cacheKey = this.getCacheKey(teamId, distinctId)
        this.personUpdateCache.delete(cacheKey)
        this.personCheckCache.delete(cacheKey)
    }

    private getCheckCachedPerson(teamId: number, distinctId: string): InternalPerson | null | undefined {
        const cacheKey = this.getCacheKey(teamId, distinctId)
        const result = this.personCheckCache.get(cacheKey)
        if (result !== undefined) {
            this.cacheMetrics.checkCacheHits++
            // Return a deep copy to prevent modifications from affecting the cached object
            return result === null
                ? null
                : {
                      ...result,
                      properties: { ...result.properties },
                      properties_last_updated_at: { ...result.properties_last_updated_at },
                      properties_last_operation: result.properties_last_operation
                          ? { ...result.properties_last_operation }
                          : {},
                      created_at: result.created_at,
                  }
        } else {
            this.cacheMetrics.checkCacheMisses++
        }
        return result
    }

    private getCachedPersonForUpdate(teamId: number, distinctId: string): PersonUpdate | null | undefined {
        const cacheKey = this.getCacheKey(teamId, distinctId)
        const result = this.personUpdateCache.get(cacheKey)
        if (result !== undefined) {
            this.cacheMetrics.updateCacheHits++
            // Return a deep copy to prevent modifications from affecting the cached object
            return result === null
                ? null
                : {
                      ...result,
                      properties: { ...result.properties },
                      properties_last_updated_at: { ...result.properties_last_updated_at },
                      properties_last_operation: result.properties_last_operation
                          ? { ...result.properties_last_operation }
                          : {},
                  }
        } else {
            this.cacheMetrics.updateCacheMisses++
            return undefined
        }
    }

    private setCachedPersonForUpdate(teamId: number, distinctId: string, person: PersonUpdate | null): void {
        const cacheKey = this.getCacheKey(teamId, distinctId)
        this.personUpdateCache.set(cacheKey, person)
    }

    private setCheckCachedPerson(teamId: number, distinctId: string, person: InternalPerson | null): void {
        const cacheKey = this.getCacheKey(teamId, distinctId)
        this.personCheckCache.set(cacheKey, person)
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
        this.incrementDatabaseOperation('createPerson', distinctIds?.[0]?.distinctId ?? '')
        const [person, messages] = await this.db.createPerson(
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
        this.setCheckCachedPerson(teamId, distinctIds?.[0]?.distinctId ?? '', person)
        this.setCachedPersonForUpdate(
            teamId,
            distinctIds?.[0]?.distinctId ?? '',
            fromInternalPerson(person, distinctIds?.[0]?.distinctId ?? '')
        )
        return [person, messages]
    }

    private addPersonUpdateToBatch(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string
    ): [InternalPerson, TopicMessage[]] {
        const existingUpdate = this.getCachedPersonForUpdate(person.team_id, distinctId)

        let personUpdate: PersonUpdate
        if (!existingUpdate) {
            // Create new PersonUpdate from the person and apply the update
            personUpdate = fromInternalPerson(person, distinctId)

            // Merge properties specifically to avoid overwriting
            if (update.properties) {
                personUpdate.properties = { ...personUpdate.properties, ...update.properties }
            }

            // Apply other updates (excluding properties which we handled above)
            const { properties, ...otherUpdates } = update
            Object.assign(personUpdate, otherUpdates)

            personUpdate.needs_write = true
            this.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
        } else {
            // Merge updates into existing cached PersonUpdate
            personUpdate = existingUpdate

            // Merge properties specifically to avoid overwriting
            if (update.properties) {
                personUpdate.properties = { ...personUpdate.properties, ...update.properties }
            }

            // Apply other updates (excluding properties which we handled above)
            const { properties, ...otherUpdates } = update
            Object.assign(personUpdate, otherUpdates)

            personUpdate.needs_write = true
            this.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
        }
        // Return the merged person from the cache
        return [toInternalPerson(personUpdate), []]
    }

    private addPersonPropertiesUpdateToBatch(
        _person: InternalPerson,
        _propertiesToSet: Properties,
        _propertiesToUnset: string[],
        _otherUpdates: Partial<InternalPerson>,
        _distinctId: string
    ): [InternalPerson, TopicMessage[]] {
        throw new Error('Not implemented')
    }

    private async updatePersonOptimistically(personUpdate: PersonUpdate): Promise<void> {
        this.incrementDatabaseOperation('updatePersonOptimistically', personUpdate.distinct_id)

        const start = performance.now()
        const actualVersion = await this.db.updatePersonOptimistically(personUpdate)
        this.recordUpdateLatency(
            'updatePersonOptimistically',
            (performance.now() - start) / 1000,
            personUpdate.distinct_id
        )
        observeLatencyByVersion(personUpdate, start, 'updatePersonOptimistically')

        if (actualVersion !== undefined) {
            // Success - optimistic update worked, update version in cache
            personUpdate.version = actualVersion
            return
        }

        // Optimistic update failed due to version mismatch
        personOptimisticUpdateConflictsPerBatchCounter.inc()

        // Fetch latest person data to get current version and properties
        this.incrementDatabaseOperation('fetchPerson', personUpdate.distinct_id)
        const latestPerson = await this.db.fetchPerson(personUpdate.team_id, personUpdate.distinct_id)

        if (latestPerson) {
            // We need to recompute our property changes against the latest person data
            // Similar to how group store uses calculateUpdate, we should use calculatePersonPropertyUpdate
            // However, since we don't store the original property operations that led to this PersonUpdate,
            // we'll do a simple merge for now - our cached properties override the latest ones
            const mergedProperties = { ...latestPerson.properties, ...personUpdate.properties }

            // Update the PersonUpdate with latest data
            personUpdate.properties = mergedProperties
            personUpdate.properties_last_updated_at = latestPerson.properties_last_updated_at || {}
            personUpdate.properties_last_operation = latestPerson.properties_last_operation || {}
            personUpdate.version = latestPerson.version
        }

        throw new Error('Optimistic update failed, will retry')
    }

    private async updatePersonWithTransaction(personUpdate: PersonUpdate, source: string): Promise<void> {
        const operation = 'updatePersonTransaction' + (source ? `-${source}` : '')
        this.incrementDatabaseOperation(operation as MethodName, personUpdate.distinct_id)

        // Convert PersonUpdate back to InternalPerson for database call
        const internalPerson = toInternalPerson(personUpdate)
        const start = performance.now()

        // Use a transaction to ensure we get the latest version with FOR UPDATE
        await this.db.postgres.transaction(PostgresUse.COMMON_WRITE, operation, async (tx) => {
            // First fetch the person with FOR UPDATE to lock the row
            const latestPerson = await this.db.fetchPerson(personUpdate.team_id, personUpdate.distinct_id, {
                forUpdate: true,
            })

            if (!latestPerson) {
                throw new Error('Person not found during direct update')
            }

            // Create update object without version field (updatePersonDeprecated handles version internally)
            const { version, ...updateFields } = internalPerson
            await this.db.updatePersonDeprecated(latestPerson, updateFields, tx, 'forUpdate')
        })
        this.recordUpdateLatency(
            'updatePersonWithTransaction',
            (performance.now() - start) / 1000,
            personUpdate.distinct_id
        )
        observeLatencyByVersion(internalPerson, start, operation)
    }

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
