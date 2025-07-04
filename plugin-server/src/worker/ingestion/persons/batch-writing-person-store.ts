import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import pLimit from 'p-limit'

import { TopicMessage } from '../../../kafka/producer'
import {
    InternalPerson,
    PersonBatchWritingDbWriteMode,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
} from '../../../types'
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
    personFallbackOperationsCounter,
    personFetchForCheckingCacheOperationsCounter,
    personFetchForUpdateCacheOperationsCounter,
    personFlushBatchSizeHistogram,
    personFlushLatencyHistogram,
    personFlushOperationsCounter,
    personMethodCallsPerBatchHistogram,
    personOptimisticUpdateConflictsPerBatchCounter,
    personWriteMethodAttemptCounter,
    totalPersonUpdateLatencyPerBatchHistogram,
} from './metrics'
import { fromInternalPerson, PersonUpdate, toInternalPerson } from './person-update-batch'
import { PersonsStore } from './persons-store'
import { PersonsStoreForBatch } from './persons-store-for-batch'

type MethodName =
    | 'fetchForChecking'
    | 'fetchForUpdate'
    | 'fetchPerson'
    | 'updatePersonAssertVersion'
    | 'updatePersonNoAssert'
    | 'updatePersonWithTransaction'
    | 'createPerson'
    | 'updatePersonWithPropertiesDiffForUpdate'
    | 'updatePersonForMerge'
    | 'deletePerson'
    | 'addDistinctId'
    | 'moveDistinctIds'
    | 'updateCohortsAndFeatureFlagsForMerge'
    | 'addPersonlessDistinctId'
    | 'addPersonlessDistinctIdForMerge'
    | 'addPersonUpdateToBatch'

type UpdateType = 'updatePersonAssertVersion' | 'updatePersonNoAssert' | 'updatePersonWithTransaction'

export interface BatchWritingPersonsStoreOptions {
    maxConcurrentUpdates: number
    dbWriteMode: PersonBatchWritingDbWriteMode
    maxOptimisticUpdateRetries: number
    optimisticUpdateRetryInterval: number
}

const DEFAULT_OPTIONS: BatchWritingPersonsStoreOptions = {
    dbWriteMode: 'NO_ASSERT',
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
    private distinctIdToPersonId: Map<string, string>
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
        this.distinctIdToPersonId = new Map()
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
        const flushStartTime = performance.now()
        const updateEntries = Array.from(this.personUpdateCache.entries()).filter(
            (entry): entry is [string, PersonUpdate] => {
                const [_, update] = entry
                return update !== null && update.needs_write
            }
        )

        const batchSize = updateEntries.length
        personFlushBatchSizeHistogram.observe({ db_write_mode: this.options.dbWriteMode }, batchSize)

        if (batchSize === 0) {
            personFlushLatencyHistogram.observe({ db_write_mode: this.options.dbWriteMode }, 0)
            personFlushOperationsCounter.inc({ db_write_mode: this.options.dbWriteMode, outcome: 'success' })
            return
        }

        const limit = pLimit(this.options.maxConcurrentUpdates)

        try {
            await Promise.all(
                updateEntries.map(([cacheKey, update]) =>
                    limit(async () => {
                        try {
                            personWriteMethodAttemptCounter.inc({
                                db_write_mode: this.options.dbWriteMode,
                                method: this.options.dbWriteMode,
                                outcome: 'attempt',
                            })

                            switch (this.options.dbWriteMode) {
                                case 'NO_ASSERT':
                                    await this.updatePersonNoAssert(update, 'batch')
                                    break
                                case 'ASSERT_VERSION':
                                    await promiseRetry(
                                        () => this.updatePersonAssertVersion(update),
                                        'updatePersonAssertVersion',
                                        this.options.maxOptimisticUpdateRetries,
                                        this.options.optimisticUpdateRetryInterval,
                                        undefined,
                                        [MessageSizeTooLarge]
                                    )
                                    break
                                case 'WITH_TRANSACTION':
                                    await promiseRetry(
                                        () => this.updatePersonWithTransaction(update, 'batch'),
                                        'updatePersonWithTransaction',
                                        this.options.maxOptimisticUpdateRetries,
                                        this.options.optimisticUpdateRetryInterval,
                                        undefined,
                                        [MessageSizeTooLarge]
                                    )
                                    break
                            }

                            personWriteMethodAttemptCounter.inc({
                                db_write_mode: this.options.dbWriteMode,
                                method: this.options.dbWriteMode,
                                outcome: 'success',
                            })
                        } catch (error) {
                            // If the Kafka message is too large, we can't retry, so we need to capture a warning and stop retrying
                            if (error instanceof MessageSizeTooLarge) {
                                await captureIngestionWarning(
                                    this.db.kafkaProducer,
                                    update.team_id,
                                    'person_upsert_message_size_too_large',
                                    {
                                        personId: update.id,
                                        distinctId: update.distinct_id,
                                    }
                                )
                                personWriteMethodAttemptCounter.inc({
                                    db_write_mode: this.options.dbWriteMode,
                                    method: this.options.dbWriteMode,
                                    outcome: 'error',
                                })
                                return
                            }

                            logger.warn('⚠️', 'Falling back to direct update after max retries', {
                                teamId: update.team_id,
                                personId: update.id,
                                distinctId: update.distinct_id,
                            })

                            personFallbackOperationsCounter.inc({
                                db_write_mode: this.options.dbWriteMode,
                                fallback_reason: 'max_retries',
                            })

                            await this.updatePersonNoAssert(update, 'conflictRetry')

                            personWriteMethodAttemptCounter.inc({
                                db_write_mode: this.options.dbWriteMode,
                                method: 'fallback',
                                outcome: 'success',
                            })
                        }
                    }).catch((error) => {
                        logger.error('Failed to update person after max retries and direct update fallback', {
                            error,
                            cacheKey,
                            teamId: update.team_id,
                            personId: update.id,
                            distinctId: update.distinct_id,
                            errorMessage: error instanceof Error ? error.message : String(error),
                            errorStack: error instanceof Error ? error.stack : undefined,
                        })

                        personWriteMethodAttemptCounter.inc({
                            db_write_mode: this.options.dbWriteMode,
                            method: 'fallback',
                            outcome: 'error',
                        })
                        throw error
                    })
                )
            )

            // Record successful flush
            const flushLatency = (performance.now() - flushStartTime) / 1000
            personFlushLatencyHistogram.observe({ db_write_mode: this.options.dbWriteMode }, flushLatency)
            personFlushOperationsCounter.inc({ db_write_mode: this.options.dbWriteMode, outcome: 'success' })
        } catch (error) {
            // Record failed flush
            const flushLatency = (performance.now() - flushStartTime) / 1000
            personFlushLatencyHistogram.observe({ db_write_mode: this.options.dbWriteMode }, flushLatency)
            personFlushOperationsCounter.inc({ db_write_mode: this.options.dbWriteMode, outcome: 'error' })

            logger.error('Failed to flush person updates', {
                error,
                errorMessage: error instanceof Error ? error.message : String(error),
                errorStack: error instanceof Error ? error.stack : undefined,
            })
            throw error
        }
    }

    async inTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T> {
        return await this.db.postgres.transaction(PostgresUse.PERSONS_WRITE, description, transaction)
    }

    async fetchForChecking(teamId: Team['id'], distinctId: string): Promise<InternalPerson | null> {
        this.incrementCount('fetchForChecking', distinctId)

        // First check the main cache
        const cachedPerson = this.getCachedPersonForUpdateByDistinctId(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson === null ? null : toInternalPerson(cachedPerson)
        }

        // Then check the checking-specific cache
        const checkCachedPerson = this.getCheckCachedPerson(teamId, distinctId)
        if (checkCachedPerson !== undefined) {
            return checkCachedPerson
        }

        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)
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

        const cachedPerson = this.getCachedPersonForUpdateByDistinctId(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson === null ? null : toInternalPerson(cachedPerson)
        }

        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)
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

    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        _tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
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
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        const [updatedPerson, kafkaMessages] = this.addPersonPropertiesUpdateToBatch(
            person,
            propertiesToSet,
            propertiesToUnset,
            otherUpdates,
            distinctId
        )
        return Promise.resolve([updatedPerson, kafkaMessages, false])
    }

    async deletePerson(person: InternalPerson, distinctId: string, tx?: TransactionClient): Promise<TopicMessage[]> {
        this.incrementCount('deletePerson', distinctId)
        this.incrementDatabaseOperation('deletePerson', distinctId)
        const start = performance.now()
        const personToDelete = this.getCachedPersonForUpdateByPersonId(person.team_id, person.id) || person

        const response = await this.db.deletePerson(personToDelete, tx)
        observeLatencyByVersion(person, start, 'deletePerson')

        // Clear ALL caches related to this person id
        this.clearAllCachesForPersonId(person.team_id, person.id)

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
        this.setDistinctIdToPersonId(person.team_id, distinctId, person.id)
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

        // Clear the cache for the source person id to ensure deleted person isn't cached
        this.clearPersonCacheForPersonId(source.team_id, source.id)

        // Update cache for the target person for the current distinct ID
        // Check if we already have cached data for the target person that includes merged properties
        const existingTargetCache = this.getCachedPersonForUpdateByPersonId(target.team_id, target.id)
        if (existingTargetCache) {
            // We have existing cached data with merged properties - preserve it
            // Create a new PersonUpdate for this distinctId that preserves the merged data
            const mergedPersonUpdate = { ...existingTargetCache, distinct_id: distinctId }
            this.setCachedPersonForUpdate(target.team_id, distinctId, mergedPersonUpdate)
        } else {
            // No existing cache, create fresh cache from target person
            this.setCachedPersonForUpdate(target.team_id, distinctId, fromInternalPerson(target, distinctId))
        }

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

    getCheckCache(): Map<string, InternalPerson | null> {
        return this.personCheckCache
    }

    getUpdateCache(): Map<string, PersonUpdate | null> {
        return this.personUpdateCache
    }

    private getDistinctCacheKey(teamId: number, distinctId: string): string {
        return `${teamId}:${distinctId}`
    }

    private getPersonIdCacheKey(teamId: number, personId: string): string {
        return `${teamId}:${personId}`
    }

    clearPersonCacheForPersonId(teamId: number, personId: string): void {
        this.personUpdateCache.delete(this.getPersonIdCacheKey(teamId, personId))
    }

    clearAllCachesForPersonId(teamId: number, personId: string): void {
        // Clear the person id cache
        this.clearPersonCacheForPersonId(teamId, personId)

        // Find and clear all distinct ID mappings that point to this person id
        const distinctIdsToRemove: string[] = []
        for (const [distinctCacheKey, mappedPersonId] of this.distinctIdToPersonId.entries()) {
            if (mappedPersonId === personId && distinctCacheKey.startsWith(`${teamId}:`)) {
                distinctIdsToRemove.push(distinctCacheKey)
            }
        }

        // Remove all distinct ID mappings and their check cache entries
        for (const distinctCacheKey of distinctIdsToRemove) {
            this.distinctIdToPersonId.delete(distinctCacheKey)
            this.personCheckCache.delete(distinctCacheKey)
        }
    }

    clearAllCachesForDistinctId(teamId: number, distinctId: string): void {
        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)
        const personId = this.distinctIdToPersonId.get(cacheKey)

        // Clear the distinct ID mapping
        this.distinctIdToPersonId.delete(cacheKey)

        // Clear the person data if we have the id
        if (personId) {
            this.clearPersonCacheForPersonId(teamId, personId)
        }

        // Clear the check cache
        this.personCheckCache.delete(cacheKey)
    }

    private getCheckCachedPerson(teamId: number, distinctId: string): InternalPerson | null | undefined {
        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)
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

    getCachedPersonForUpdateByPersonId(teamId: number, personId: string | undefined): PersonUpdate | null | undefined {
        if (personId === undefined) {
            this.cacheMetrics.updateCacheMisses++
            return undefined
        }

        const result = this.personUpdateCache.get(this.getPersonIdCacheKey(teamId, personId))
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
                      properties_to_set: { ...result.properties_to_set },
                      properties_to_unset: [...result.properties_to_unset],
                  }
        } else {
            this.cacheMetrics.updateCacheMisses++
            return undefined
        }
    }

    getCachedPersonForUpdateByDistinctId(teamId: number, distinctId: string): PersonUpdate | null | undefined {
        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)
        const personId = this.distinctIdToPersonId.get(cacheKey)

        return this.getCachedPersonForUpdateByPersonId(teamId, personId)
    }

    setCachedPersonForUpdate(teamId: number, distinctId: string, person: PersonUpdate | null): void {
        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)

        if (person === null) {
            // Remove mappings when person is null
            const existingPersonId = this.distinctIdToPersonId.get(cacheKey)
            this.distinctIdToPersonId.delete(cacheKey)
            if (existingPersonId) {
                this.personUpdateCache.set(this.getPersonIdCacheKey(teamId, existingPersonId), null)
            }
            return
        }

        // Set the distinct ID -> person id mapping
        this.distinctIdToPersonId.set(cacheKey, person.id)

        // Check if we already have cached data for this person id
        const existingPersonUpdate = this.personUpdateCache.get(this.getPersonIdCacheKey(teamId, person.id))

        if (existingPersonUpdate) {
            // Merge the properties and changesets from both updates
            const mergedPersonUpdate = this.mergeUpdateIntoPersonUpdate(existingPersonUpdate, {
                properties: person.properties,
                is_identified: person.is_identified,
            } as Partial<InternalPerson>)

            // Handle fields that are specific to PersonUpdate - merge properties_to_set and properties_to_unset
            mergedPersonUpdate.properties_to_set = {
                ...existingPersonUpdate.properties_to_set,
                ...person.properties_to_set,
            }
            mergedPersonUpdate.properties_to_unset = [
                ...new Set([...existingPersonUpdate.properties_to_unset, ...person.properties_to_unset]),
            ]

            this.personUpdateCache.set(this.getPersonIdCacheKey(teamId, person.id), mergedPersonUpdate)
        } else {
            // First time we're caching this person id
            this.personUpdateCache.set(this.getPersonIdCacheKey(teamId, person.id), person)
        }
    }

    setCheckCachedPerson(teamId: number, distinctId: string, person: InternalPerson | null): void {
        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)
        this.personCheckCache.set(cacheKey, person)
    }

    setDistinctIdToPersonId(teamId: number, distinctId: string, personId: string): void {
        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)
        this.distinctIdToPersonId.set(cacheKey, personId)
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

    async populatePersonStore(teamId: Team['id'], distinctId: string): Promise<void> {
        const person = await this.fetchForUpdate(teamId, distinctId)
        this.setCheckCachedPerson(teamId, distinctId, person)
        this.setCachedPersonForUpdate(teamId, distinctId, person ? fromInternalPerson(person, distinctId) : null)
    }

    private addPersonUpdateToBatch(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string
    ): [InternalPerson, TopicMessage[], boolean] {
        const existingUpdate = this.getCachedPersonForUpdateByDistinctId(person.team_id, distinctId)

        let personUpdate: PersonUpdate
        if (!existingUpdate) {
            // Create new PersonUpdate from the person and apply the update
            personUpdate = fromInternalPerson(person, distinctId)
            personUpdate = this.mergeUpdateIntoPersonUpdate(personUpdate, update)
            this.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
        } else {
            // Merge updates into existing cached PersonUpdate
            personUpdate = this.mergeUpdateIntoPersonUpdate(existingUpdate, update)
            this.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
        }
        // Return the merged person from the cache
        return [toInternalPerson(personUpdate), [], false]
    }

    /**
     * Helper method to merge an update into a PersonUpdate
     * Handles properties and is_identified merging with proper logic
     */
    private mergeUpdateIntoPersonUpdate(personUpdate: PersonUpdate, update: Partial<InternalPerson>): PersonUpdate {
        // For properties, we track them in the fine-grained properties_to_set/unset
        if (update.properties) {
            // Add all properties from the update to properties_to_set
            Object.entries(update.properties).forEach(([key, value]) => {
                personUpdate.properties_to_set[key] = value
                // Remove from unset list if it was there
                const unsetIndex = personUpdate.properties_to_unset.indexOf(key)
                if (unsetIndex !== -1) {
                    personUpdate.properties_to_unset.splice(unsetIndex, 1)
                }
            })
        }

        // Apply other updates (excluding properties which we handled above)
        const { properties, is_identified, ...otherUpdates } = update
        Object.assign(personUpdate, otherUpdates)

        // Handle is_identified specially with || operator
        if (is_identified !== undefined) {
            personUpdate.is_identified = personUpdate.is_identified || is_identified
        }

        personUpdate.needs_write = true

        return personUpdate
    }

    private addPersonPropertiesUpdateToBatch(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string
    ): [InternalPerson, TopicMessage[]] {
        const existingUpdate = this.getCachedPersonForUpdateByDistinctId(person.team_id, distinctId)

        let personUpdate: PersonUpdate
        if (!existingUpdate) {
            // Create new PersonUpdate from the person
            personUpdate = fromInternalPerson(person, distinctId)
        } else {
            // Use existing cached PersonUpdate
            personUpdate = { ...existingUpdate }
        }

        // Add properties to set (merge with existing properties_to_set)
        Object.entries(propertiesToSet).forEach(([key, value]) => {
            personUpdate.properties_to_set[key] = value
            // Remove from unset list if it was there
            const unsetIndex = personUpdate.properties_to_unset.indexOf(key)
            if (unsetIndex !== -1) {
                personUpdate.properties_to_unset.splice(unsetIndex, 1)
            }
        })

        // Add properties to unset (merge with existing properties_to_unset)
        propertiesToUnset.forEach((key) => {
            if (!personUpdate.properties_to_unset.includes(key)) {
                personUpdate.properties_to_unset.push(key)
            }
            // Remove from set list if it was there
            delete personUpdate.properties_to_set[key]
        })

        // Apply other updates
        Object.assign(personUpdate, otherUpdates)

        // Handle is_identified specially with || operator
        if (otherUpdates.is_identified !== undefined) {
            personUpdate.is_identified = personUpdate.is_identified || otherUpdates.is_identified
        }

        personUpdate.needs_write = true

        this.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
        return [toInternalPerson(personUpdate), []]
    }

    private async updatePersonNoAssert(
        personUpdate: PersonUpdate,
        source: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        const operation = 'updatePersonNoAssert' + (source ? `-${source}` : '')
        this.incrementDatabaseOperation(operation as MethodName, personUpdate.distinct_id)
        // Convert PersonUpdate back to InternalPerson for database call
        const person = toInternalPerson(personUpdate)
        // Create update object without version field (updatePerson handles version internally)
        const { version, ...updateFields } = person

        this.incrementCount('updatePersonNoAssert', personUpdate.distinct_id)
        this.incrementDatabaseOperation('updatePersonNoAssert', personUpdate.distinct_id)
        const start = performance.now()
        const response = await this.db.updatePerson(person, updateFields, undefined, 'updatePersonNoAssert')
        this.recordUpdateLatency('updatePersonNoAssert', (performance.now() - start) / 1000, personUpdate.distinct_id)
        observeLatencyByVersion(person, start, 'updatePersonNoAssert')
        return response
    }

    /**
     * Updates the person in the database by attempting to write to a column where the version is the stored cached
     * version. If no rows to update are found, the update fails and we retry by reading again from the database.
     * This method uses no locks but can cause multiple reads from the database.
     * @param personUpdate the personUpdate to write
     * @returns the actual version of the person after the write
     */
    private async updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<void> {
        this.incrementDatabaseOperation('updatePersonAssertVersion', personUpdate.distinct_id)

        const start = performance.now()
        const actualVersion = await this.db.updatePersonAssertVersion(personUpdate)
        this.recordUpdateLatency(
            'updatePersonAssertVersion',
            (performance.now() - start) / 1000,
            personUpdate.distinct_id
        )
        observeLatencyByVersion(personUpdate, start, 'updatePersonAssertVersion')

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
            // Use fine-grained merge: start with latest properties from DB and apply our specific changes
            const mergedProperties = { ...latestPerson.properties }

            // Apply our properties_to_set
            Object.entries(personUpdate.properties_to_set).forEach(([key, value]) => {
                mergedProperties[key] = value
            })

            // Apply our properties_to_unset
            personUpdate.properties_to_unset.forEach((key) => {
                delete mergedProperties[key]
            })

            // Update the PersonUpdate with latest data and merged properties
            personUpdate.properties = mergedProperties
            personUpdate.properties_last_updated_at = latestPerson.properties_last_updated_at || {}
            personUpdate.properties_last_operation = latestPerson.properties_last_operation || {}
            personUpdate.version = latestPerson.version
        }

        throw new Error('Assert version update failed, will retry')
    }

    private async updatePersonWithTransaction(personUpdate: PersonUpdate, source: string): Promise<void> {
        const operation = 'updatePersonTransaction' + (source ? `-${source}` : '')
        this.incrementDatabaseOperation(operation as MethodName, personUpdate.distinct_id)

        // Convert PersonUpdate back to InternalPerson for database call
        const internalPerson = toInternalPerson(personUpdate)
        const start = performance.now()

        // Use a transaction to ensure we get the latest version with FOR UPDATE
        await this.db.postgres.transaction(PostgresUse.PERSONS_WRITE, operation, async (tx) => {
            // First fetch the person with FOR UPDATE to lock the row
            const latestPerson = await this.db.fetchPerson(personUpdate.team_id, personUpdate.distinct_id, {
                forUpdate: true,
            })

            if (!latestPerson) {
                throw new Error('Person not found during direct update')
            }

            // Create update object without version field (updatePerson handles version internally)
            const { version, ...updateFields } = internalPerson
            await this.db.updatePerson(latestPerson, updateFields, tx, 'forUpdate')
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
