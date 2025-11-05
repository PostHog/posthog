import { DateTime } from 'luxon'
import pLimit from 'p-limit'

import { Properties } from '@posthog/plugin-scaffold'

import { NoRowsUpdatedError } from '~/utils/utils'

import { KafkaProducerWrapper, TopicMessage } from '../../../kafka/producer'
import {
    InternalPerson,
    PersonBatchWritingDbWriteMode,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
} from '../../../types'
import { CreatePersonResult, MoveDistinctIdsResult } from '../../../utils/db/db'
import { MessageSizeTooLarge } from '../../../utils/db/error'
import { logger } from '../../../utils/logger'
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
    personProfileBatchIgnoredPropertiesCounter,
    personProfileBatchUpdateOutcomeCounter,
    personPropertyKeyUpdateCounter,
    personWriteMethodAttemptCounter,
    totalPersonUpdateLatencyPerBatchHistogram,
} from './metrics'
import { eventToPersonProperties } from './person-property-utils'
import { getMetricKey } from './person-update'
import { PersonUpdate, fromInternalPerson, toInternalPerson } from './person-update-batch'
import { PersonsStore } from './persons-store'
import { FlushResult, PersonsStoreForBatch } from './persons-store-for-batch'
import { PersonsStoreTransaction } from './persons-store-transaction'
import { PersonPropertiesSizeViolationError, PersonRepository } from './repositories/person-repository'
import { PersonRepositoryTransaction } from './repositories/person-repository-transaction'

type MethodName =
    | 'fetchForChecking'
    | 'fetchForUpdate'
    | 'fetchPerson'
    | 'updatePersonAssertVersion'
    | 'updatePersonNoAssert'
    | 'createPerson'
    | 'updatePersonWithPropertiesDiffForUpdate'
    | 'updatePersonForMerge'
    | 'deletePerson'
    | 'addDistinctId'
    | 'moveDistinctIds'
    | 'fetchPersonDistinctIds'
    | 'updateCohortsAndFeatureFlagsForMerge'
    | 'addPersonlessDistinctId'
    | 'addPersonlessDistinctIdForMerge'
    | 'addPersonUpdateToBatch'

type UpdateType = 'updatePersonAssertVersion' | 'updatePersonNoAssert'

interface PersonUpdateResult {
    success: boolean
    messages: TopicMessage[]
    // If there's a updated person update, it will be returned here.
    // This is useful for the optimistic update case, where we need to update the cache with the latest version.
    personUpdate?: PersonUpdate
}

class MaxRetriesError extends Error {
    constructor(
        message: string,
        public latestPersonUpdate: PersonUpdate
    ) {
        super(message)
        this.name = 'MaxRetriesError'
    }
}

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

    constructor(
        private personRepository: PersonRepository,
        private kafkaProducer: KafkaProducerWrapper,
        options?: Partial<BatchWritingPersonsStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
    }

    forBatch(): PersonsStoreForBatch {
        return new BatchWritingPersonsStoreForBatch(this.personRepository, this.kafkaProducer, this.options)
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

    constructor(
        private personRepository: PersonRepository,
        private kafkaProducer: KafkaProducerWrapper,
        options?: Partial<BatchWritingPersonsStoreOptions>
    ) {
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

    /**
     * Check if a person update should trigger a database write.
     * Returns the outcome: 'changed' (should write), 'ignored' (filtered properties only), or 'no_change' (no properties changed)
     *
     * Also tracks metrics for ignored properties at the batch level.
     */
    private getPersonUpdateOutcome(update: PersonUpdate): 'changed' | 'ignored' | 'no_change' {
        const hasNonPropertyChanges =
            update.is_identified !== update.original_is_identified ||
            !update.created_at.equals(update.original_created_at)

        if (hasNonPropertyChanges) {
            return 'changed'
        }

        const hasPropertyChanges =
            Object.keys(update.properties_to_set).length > 0 || update.properties_to_unset.length > 0

        if (!hasPropertyChanges) {
            return 'no_change'
        }

        // If there are properties to unset, always write
        if (update.properties_to_unset.length > 0) {
            return 'changed'
        }

        // Check if there are any properties_to_set that should trigger an update
        const ignoredProperties: string[] = []
        const hasPropertyTriggeringUpdate = Object.keys(update.properties_to_set).some((key) => {
            // Check if this is a new property (not in current properties)
            const isNewProperty = !(key in update.properties)
            const valueChanged = update.properties[key] !== update.properties_to_set[key]

            if (!valueChanged) {
                return false
            }

            if (isNewProperty) {
                return true
            }

            const isFiltered = eventToPersonProperties.has(key) || key.startsWith('$geoip_')
            if (isFiltered) {
                ignoredProperties.push(key)
                return false
            }
            return true
        })

        if (!hasPropertyTriggeringUpdate) {
            // Only track as ignored if ALL properties are filtered
            ignoredProperties.forEach((property) => {
                personProfileBatchIgnoredPropertiesCounter.labels({ property }).inc()
            })
            return 'ignored'
        }

        return 'changed'
    }

    async flush(): Promise<FlushResult[]> {
        const flushStartTime = performance.now()

        // Track outcomes for all person updates that were actually modified and filter to only those that should write
        const updateEntries = Array.from(this.personUpdateCache.entries()).filter(
            (entry): entry is [string, PersonUpdate] => {
                const [_, update] = entry

                // Skip null entries - these are deleted persons or cleared cache entries
                if (!update) {
                    return false
                }

                // Skip entries not marked for write - these are read-only cache entries from fetchForUpdate
                // that were cached but never modified (no events tried to update their properties)
                if (!update.needs_write) {
                    return false
                }

                // Determine outcome and track metrics for this person update
                const outcome = this.getPersonUpdateOutcome(update)
                personProfileBatchUpdateOutcomeCounter.labels({ outcome }).inc()

                // Track which property keys caused person updates (only for 'changed' outcomes)
                if (outcome === 'changed') {
                    const metricsKeys = new Set<string>()
                    Object.keys(update.properties_to_set).forEach((key) => {
                        metricsKeys.add(getMetricKey(key))
                    })
                    update.properties_to_unset.forEach((key) => {
                        metricsKeys.add(getMetricKey(key))
                    })
                    metricsKeys.forEach((key) => personPropertyKeyUpdateCounter.labels({ key: key }).inc())
                }

                // Only write to database if outcome is 'changed'
                return outcome === 'changed'
            }
        )

        const batchSize = updateEntries.length
        personFlushBatchSizeHistogram.observe({ db_write_mode: this.options.dbWriteMode }, batchSize)

        if (batchSize === 0) {
            personFlushLatencyHistogram.observe({ db_write_mode: this.options.dbWriteMode }, 0)
            personFlushOperationsCounter.inc({ db_write_mode: this.options.dbWriteMode, outcome: 'success' })
            return []
        }

        const limit = pLimit(this.options.maxConcurrentUpdates)

        try {
            const results = await Promise.all(
                updateEntries.map(([cacheKey, update]) =>
                    limit(async (): Promise<FlushResult[]> => {
                        try {
                            personWriteMethodAttemptCounter.inc({
                                db_write_mode: this.options.dbWriteMode,
                                method: this.options.dbWriteMode,
                                outcome: 'attempt',
                            })

                            let kafkaMessages: FlushResult[] = []
                            switch (this.options.dbWriteMode) {
                                case 'NO_ASSERT': {
                                    const result = await this.withMergeRetry(
                                        update,
                                        this.updatePersonNoAssert.bind(this),
                                        'updatePersonNoAssert',
                                        this.options.maxOptimisticUpdateRetries,
                                        this.options.optimisticUpdateRetryInterval
                                    )
                                    kafkaMessages = result.messages.map((message) => ({
                                        topicMessage: message,
                                        teamId: update.team_id,
                                        uuid: update.uuid,
                                        distinctId: update.distinct_id,
                                    }))
                                    break
                                }
                                case 'ASSERT_VERSION': {
                                    const result = await this.withMergeRetry(
                                        update,
                                        this.updatePersonAssertVersion.bind(this),
                                        'updatePersonAssertVersion',
                                        this.options.maxOptimisticUpdateRetries,
                                        this.options.optimisticUpdateRetryInterval
                                    )
                                    kafkaMessages = result.messages.map((message) => ({
                                        topicMessage: message,
                                        teamId: update.team_id,
                                        uuid: update.uuid,
                                        distinctId: update.distinct_id,
                                    }))
                                    break
                                }
                            }

                            personWriteMethodAttemptCounter.inc({
                                db_write_mode: this.options.dbWriteMode,
                                method: this.options.dbWriteMode,
                                outcome: 'success',
                            })

                            return kafkaMessages
                        } catch (error) {
                            // If the Kafka message is too large, we can't retry, so we need to capture a warning and stop retrying
                            if (error instanceof MessageSizeTooLarge) {
                                await captureIngestionWarning(
                                    this.kafkaProducer,
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
                                return []
                            }

                            if (error instanceof PersonPropertiesSizeViolationError) {
                                await captureIngestionWarning(
                                    this.kafkaProducer,
                                    update.team_id,
                                    'person_properties_size_violation',
                                    {
                                        personId: update.id,
                                        distinctId: update.distinct_id,
                                        teamId: update.team_id,
                                        message: 'Person properties exceeds size limit and was rejected',
                                    }
                                )
                                personWriteMethodAttemptCounter.inc({
                                    db_write_mode: this.options.dbWriteMode,
                                    method: this.options.dbWriteMode,
                                    outcome: 'properties_size_violation',
                                })
                                return []
                            }

                            // Handle max retries error with the latest person update
                            if (error instanceof MaxRetriesError) {
                                logger.warn('⚠️', 'Falling back to direct update after max retries', {
                                    teamId: error.latestPersonUpdate.team_id,
                                    personId: error.latestPersonUpdate.id,
                                    distinctId: error.latestPersonUpdate.distinct_id,
                                })

                                personFallbackOperationsCounter.inc({
                                    db_write_mode: this.options.dbWriteMode,
                                    fallback_reason: 'max_retries',
                                })

                                const fallbackResult = await this.updatePersonNoAssert(error.latestPersonUpdate)
                                const fallbackMessages = fallbackResult.success ? fallbackResult.messages : []

                                personWriteMethodAttemptCounter.inc({
                                    db_write_mode: this.options.dbWriteMode,
                                    method: 'fallback',
                                    outcome: 'success',
                                })

                                return fallbackMessages.map((message) => ({
                                    topicMessage: message,
                                    teamId: error.latestPersonUpdate.team_id,
                                    uuid: error.latestPersonUpdate.uuid,
                                    distinctId: error.latestPersonUpdate.distinct_id,
                                }))
                            }

                            // Re-throw any other errors
                            throw error
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

            // Flatten all Kafka messages from all operations
            const allKafkaMessages = results.flat()

            // Record successful flush
            const flushLatency = (performance.now() - flushStartTime) / 1000
            personFlushLatencyHistogram.observe({ db_write_mode: this.options.dbWriteMode }, flushLatency)
            personFlushOperationsCounter.inc({ db_write_mode: this.options.dbWriteMode, outcome: 'success' })

            return allKafkaMessages
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

    async inTransaction<T>(description: string, transaction: (tx: PersonsStoreTransaction) => Promise<T>): Promise<T> {
        return await this.personRepository.inTransaction(description, async (tx) => {
            const transactionWrapper = new PersonsStoreTransaction(this, tx)
            return await transaction(transactionWrapper)
        })
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
                    const person = await this.personRepository.fetchPerson(teamId, distinctId, { useReadReplica: true })
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
                    const person = await this.personRepository.fetchPerson(teamId, distinctId, {
                        useReadReplica: false,
                    })
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
        _tx?: PersonRepositoryTransaction
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
        _tx?: PersonRepositoryTransaction
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

    async deletePerson(
        person: InternalPerson,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<TopicMessage[]> {
        this.incrementCount('deletePerson', distinctId)
        this.incrementDatabaseOperation('deletePerson', distinctId)
        const start = performance.now()
        const cachedPersonUpdate = this.getCachedPersonForUpdateByPersonId(person.team_id, person.id)
        const personToDelete = cachedPersonUpdate ? toInternalPerson(cachedPersonUpdate) : person

        const response = await (tx || this.personRepository).deletePerson(personToDelete)
        observeLatencyByVersion(person, start, 'deletePerson')

        // Clear ALL caches related to this person id
        this.clearAllCachesForPersonId(person.team_id, person.id)

        return response
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: PersonRepositoryTransaction
    ): Promise<TopicMessage[]> {
        this.incrementCount('addDistinctId', distinctId)
        this.incrementDatabaseOperation('addDistinctId', distinctId)
        const start = performance.now()
        const response = await (tx || this.personRepository).addDistinctId(person, distinctId, version)
        observeLatencyByVersion(person, start, 'addDistinctId')
        this.setDistinctIdToPersonId(person.team_id, distinctId, person.id)
        return response
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction
    ): Promise<MoveDistinctIdsResult> {
        this.incrementCount('moveDistinctIds', distinctId)
        this.incrementDatabaseOperation('moveDistinctIds', distinctId)
        const start = performance.now()
        const response = await tx.moveDistinctIds(source, target, limit)
        observeLatencyByVersion(target, start, 'moveDistinctIds')

        // Clear the cache for the source person id to ensure deleted person isn't cached
        this.clearAllCachesForPersonId(source.team_id, source.id)

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
        if (response.success) {
            for (const distinctId of response.distinctIdsMoved) {
                this.setDistinctIdToPersonId(target.team_id, distinctId, target.id)
            }
        }

        return response
    }

    async fetchPersonDistinctIds(
        person: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction
    ): Promise<string[]> {
        this.incrementCount('fetchPersonDistinctIds', distinctId)
        this.incrementDatabaseOperation('fetchPersonDistinctIds', distinctId)
        const start = performance.now()
        const response = await tx.fetchPersonDistinctIds(person, limit)
        observeLatencyByVersion(person, start, 'fetchPersonDistinctIds')

        return response
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void> {
        this.incrementCount('updateCohortsAndFeatureFlagsForMerge', distinctId)
        await (tx || this.personRepository).updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID)
    }

    async addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean> {
        this.incrementCount('addPersonlessDistinctId', distinctId)
        return await this.personRepository.addPersonlessDistinctId(teamId, distinctId)
    }

    async addPersonlessDistinctIdForMerge(
        teamId: Team['id'],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<boolean> {
        this.incrementCount('addPersonlessDistinctIdForMerge', distinctId)
        return await (tx || this.personRepository).addPersonlessDistinctIdForMerge(teamId, distinctId)
    }

    async personPropertiesSize(personId: string): Promise<number> {
        return await this.personRepository.personPropertiesSize(personId)
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

    removeDistinctIdFromCache(teamId: number, distinctId: string): void {
        this.distinctIdToPersonId.delete(this.getDistinctCacheKey(teamId, distinctId))
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
            const mergedPersonUpdate = this.mergeUpdateIntoPersonUpdate(
                existingPersonUpdate,
                {
                    properties: person.properties,
                    is_identified: person.is_identified,
                } as Partial<InternalPerson>,
                false
            )

            // Handle fields that are specific to PersonUpdate - merge properties_to_set and properties_to_unset
            mergedPersonUpdate.properties_to_set = {
                ...existingPersonUpdate.properties_to_set,
                ...person.properties_to_set,
            }
            mergedPersonUpdate.properties_to_unset = [
                ...new Set([...existingPersonUpdate.properties_to_unset, ...person.properties_to_unset]),
            ]

            mergedPersonUpdate.created_at = DateTime.min(existingPersonUpdate.created_at, person.created_at)
            mergedPersonUpdate.needs_write = existingPersonUpdate.needs_write || person.needs_write

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
        tx?: PersonRepositoryTransaction
    ): Promise<CreatePersonResult> {
        this.incrementCount('createPerson', distinctIds?.[0].distinctId ?? '')
        this.incrementDatabaseOperation('createPerson', distinctIds?.[0]?.distinctId ?? '')
        const result = await (tx || this.personRepository).createPerson(
            createdAt,
            properties,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            distinctIds
        )

        if (result.success) {
            const { person } = result
            this.setCheckCachedPerson(teamId, distinctIds?.[0]?.distinctId ?? '', person)
            this.setCachedPersonForUpdate(
                teamId,
                distinctIds?.[0]?.distinctId ?? '',
                fromInternalPerson(person, distinctIds?.[0]?.distinctId ?? '')
            )
            if (distinctIds?.[1]) {
                this.setDistinctIdToPersonId(teamId, distinctIds[1].distinctId, person.id)
                this.setCachedPersonForUpdate(
                    teamId,
                    distinctIds[1].distinctId,
                    fromInternalPerson(person, distinctIds[1].distinctId)
                )
            }
        }

        return result
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
            personUpdate = this.mergeUpdateIntoPersonUpdate(personUpdate, update, true)
            personUpdate.id = person.id
            this.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
        } else {
            // Merge updates into existing cached PersonUpdate
            personUpdate = this.mergeUpdateIntoPersonUpdate(existingUpdate, update, true)
            personUpdate.id = person.id
            this.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
        }
        // Return the merged person from the cache
        return [toInternalPerson(personUpdate), [], false]
    }

    /**
     * Helper method to merge an update into a PersonUpdate
     * Handles properties and is_identified merging with proper logic
     */
    private mergeUpdateIntoPersonUpdate(
        personUpdate: PersonUpdate,
        update: Partial<InternalPerson>,
        allowCreatedAtUpdate: boolean = false
    ): PersonUpdate {
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
        const fieldsToExclude = ['properties', 'is_identified']
        if (!allowCreatedAtUpdate) {
            fieldsToExclude.push('created_at')
        }

        const otherUpdates = Object.fromEntries(
            Object.entries(update).filter(([key]) => !fieldsToExclude.includes(key))
        )
        if (allowCreatedAtUpdate) {
            // Get minimum of existing and new created_at
            if (update.created_at) {
                if (personUpdate.created_at) {
                    otherUpdates.created_at =
                        personUpdate.created_at < update.created_at ? personUpdate.created_at : update.created_at
                } else {
                    otherUpdates.created_at = update.created_at
                }
            }
        }
        Object.assign(personUpdate, otherUpdates)

        // Handle is_identified specially with || operator
        if (update.is_identified !== undefined) {
            personUpdate.is_identified = personUpdate.is_identified || update.is_identified
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

        // Handle is_identified specially with || operator
        if (otherUpdates.is_identified !== undefined) {
            personUpdate.is_identified = personUpdate.is_identified || otherUpdates.is_identified
        }

        personUpdate.needs_write = true

        this.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
        return [toInternalPerson(personUpdate), []]
    }

    private async updatePersonNoAssert(personUpdate: PersonUpdate): Promise<PersonUpdateResult> {
        const operation = 'updatePersonNoAssert'
        this.incrementDatabaseOperation(operation as MethodName, personUpdate.distinct_id)
        // Convert PersonUpdate back to InternalPerson for database call
        const person = toInternalPerson(personUpdate)
        // Create update object without version field (updatePerson handles version internally)
        const { version, ...updateFields } = person

        this.incrementCount('updatePersonNoAssert', personUpdate.distinct_id)
        this.incrementDatabaseOperation('updatePersonNoAssert', personUpdate.distinct_id)
        const start = performance.now()

        const [_, messages] = await this.personRepository.updatePerson(person, updateFields, 'updatePersonNoAssert')
        this.recordUpdateLatency('updatePersonNoAssert', (performance.now() - start) / 1000, personUpdate.distinct_id)
        observeLatencyByVersion(person, start, 'updatePersonNoAssert')

        // updatePersonNoAssert always succeeds (no version conflicts)
        return { success: true, messages }
    }

    /**
     * Updates the person in the database by attempting to write to a column where the version is the stored cached
     * version. If no rows to update are found, the update fails and we retry by reading again from the database.
     * This method uses no locks but can cause multiple reads from the database.
     * @param personUpdate the personUpdate to write
     * @returns the actual version of the person after the write
     */
    private async updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<PersonUpdateResult> {
        this.incrementDatabaseOperation('updatePersonAssertVersion', personUpdate.distinct_id)

        const start = performance.now()

        const [actualVersion, kafkaMessages] = await this.personRepository.updatePersonAssertVersion(personUpdate)
        this.recordUpdateLatency(
            'updatePersonAssertVersion',
            (performance.now() - start) / 1000,
            personUpdate.distinct_id
        )
        observeLatencyByVersion(personUpdate, start, 'updatePersonAssertVersion')

        if (actualVersion !== undefined) {
            // Success - optimistic update worked, create updated PersonUpdate with new version
            const updatedPersonUpdate: PersonUpdate = {
                ...personUpdate,
                version: actualVersion,
            }
            return { success: true, messages: kafkaMessages, personUpdate: updatedPersonUpdate }
        }

        // Optimistic update failed due to version mismatch
        personOptimisticUpdateConflictsPerBatchCounter.inc()

        // Fetch latest person data to get current version and properties
        this.incrementDatabaseOperation('fetchPerson', personUpdate.distinct_id)
        const latestPerson = await this.personRepository.fetchPerson(personUpdate.team_id, personUpdate.distinct_id)

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

            // Create updated PersonUpdate with latest data and merged properties (without mutating input)
            const updatedPersonUpdate: PersonUpdate = {
                ...personUpdate,
                properties: mergedProperties,
                version: latestPerson.version,
                uuid: latestPerson.uuid,
                created_at: latestPerson.created_at,
                is_identified: latestPerson.is_identified || personUpdate.is_identified,
            }

            return { success: false, messages: [], personUpdate: updatedPersonUpdate }
        }

        // If we couldn't fetch the latest person, return failure without a person update
        return { success: false, messages: [] }
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

    /**
     * Retry wrapper that handles both update conflicts and person merges.
     */
    private async withMergeRetry(
        personUpdate: PersonUpdate,
        updateFn: (personUpdate: PersonUpdate) => Promise<PersonUpdateResult>,
        operation: string,
        maxRetries: number,
        retryInterval: number
    ): Promise<PersonUpdateResult> {
        let attempt = 0
        let currentPersonUpdate = personUpdate

        while (attempt <= maxRetries) {
            try {
                const result = await updateFn(currentPersonUpdate)

                if (result.success) {
                    return result
                }

                // Update failed, handle retry logic
                attempt++
                // If there's a person update, we need to update the cache with the latest version
                if (result.personUpdate) {
                    currentPersonUpdate = result.personUpdate
                }

                if (attempt <= maxRetries) {
                    logger.debug(`Optimistic update conflict for ${operation}, retrying...`, {
                        attempt,
                        maxRetries,
                        teamId: currentPersonUpdate.team_id,
                        personId: currentPersonUpdate.id,
                        distinctId: currentPersonUpdate.distinct_id,
                    })

                    await new Promise((resolve) => setTimeout(resolve, retryInterval))
                    continue
                }

                // Max retries reached, throw error to trigger fallback
                throw new MaxRetriesError(`Max retries reached for ${operation}`, currentPersonUpdate)
            } catch (error) {
                attempt++

                if (attempt <= maxRetries) {
                    // Handle person merge scenarios with special logic
                    if (error instanceof NoRowsUpdatedError) {
                        const refreshedPersonUpdate = await this.refreshPersonIdAfterMerge(currentPersonUpdate)
                        if (refreshedPersonUpdate) {
                            currentPersonUpdate = refreshedPersonUpdate
                            continue
                        }
                        // If we can't refresh the person ID, we can't retry, fail gracefully
                        return { success: true, messages: [] }
                    }

                    // Don't retry size violations - they will never succeed
                    // throw the error so that we capture an ingestion warning
                    if (error instanceof PersonPropertiesSizeViolationError) {
                        throw error
                    }

                    // For any other error type, still retry but with generic logging
                    logger.warn(`Database error for ${operation}, retrying...`, {
                        attempt,
                        maxRetries,
                        teamId: currentPersonUpdate.team_id,
                        personId: currentPersonUpdate.id,
                        distinctId: currentPersonUpdate.distinct_id,
                        error: error instanceof Error ? error.message : String(error),
                    })

                    await new Promise((resolve) => setTimeout(resolve, retryInterval))
                    continue
                }

                throw error
            }
        }

        // This should never be reached, but TypeScript requires it
        throw new Error('Unexpected end of retry loop')
    }

    /**
     * Refreshes the person ID for a given distinct ID by fetching from the database.
     * This handles cases where the person was merged and the ID changed.
     * @param personUpdate the PersonUpdate that failed to update
     * @returns updated PersonUpdate with new person ID if found, null if person no longer exists
     */
    private async refreshPersonIdAfterMerge(personUpdate: PersonUpdate): Promise<PersonUpdate | null> {
        const currentPerson = await this.personRepository.fetchPerson(personUpdate.team_id, personUpdate.distinct_id)

        if (!currentPerson) {
            // Person truly doesn't exist anymore
            return null
        }

        // Clear the old person ID from cache since it's been merged
        this.clearPersonCacheForPersonId(personUpdate.team_id, personUpdate.id)

        // Update our cache mapping to reflect the new person ID
        this.setDistinctIdToPersonId(personUpdate.team_id, personUpdate.distinct_id, currentPerson.id)

        // Create updated PersonUpdate with the new person ID and version
        const updatedPersonUpdate: PersonUpdate = {
            id: currentPerson.id,
            team_id: personUpdate.team_id,
            uuid: currentPerson.uuid,
            distinct_id: personUpdate.distinct_id,
            properties: currentPerson.properties,
            properties_last_updated_at: personUpdate.properties_last_updated_at,
            properties_last_operation: personUpdate.properties_last_operation,
            created_at: currentPerson.created_at,
            version: currentPerson.version,
            is_identified: currentPerson.is_identified || personUpdate.is_identified,
            is_user_id: personUpdate.is_user_id,
            needs_write: personUpdate.needs_write,
            properties_to_set: personUpdate.properties_to_set,
            properties_to_unset: personUpdate.properties_to_unset,
            original_is_identified: personUpdate.original_is_identified,
            original_created_at: personUpdate.original_created_at,
        }

        return updatedPersonUpdate
    }
}
