import { DateTime } from 'luxon'
import pLimit from 'p-limit'

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
} from '~/common/persons/metrics'
import { isFilteredPersonUpdateProperty } from '~/common/persons/person-property-utils'
import { PersonUpdate, fromInternalPerson, toInternalPerson } from '~/common/persons/person-update-batch'
import {
    PersonMessage,
    PersonPropertiesSizeViolationError,
    PersonRepository,
} from '~/common/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/common/utils/db/db'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { logger } from '~/common/utils/logger'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { Component } from '~/ingestion/common/scopes'
import { BatchWritingStore, BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { PersonBatchWritingDbWriteMode } from '~/ingestion/config'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'

import { PersonOutputs } from './person-context'
import { getMetricKey } from './person-update'
import { FlushResult, PersonsStore } from './persons-store'
import { PersonsStoreTransaction } from './persons-store-transaction'

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
    messages: PersonMessage[]
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
    /** When true, use batch SQL queries for person updates. When false, use individual queries. */
    useBatchUpdates: boolean
    maxOptimisticUpdateRetries: number
    optimisticUpdateRetryInterval: number
    /** When true, all property changes trigger person updates (disables batch-level filtering) */
    updateAllProperties: boolean
    /**
     * Interval at which accumulated per-distinct_id metrics are emitted and
     * cleared. Set to 0 to disable the timer (used by tests; production
     * always wants a positive interval).
     */
    metricEmissionIntervalMs: number
}

const DEFAULT_OPTIONS: BatchWritingPersonsStoreOptions = {
    dbWriteMode: 'NO_ASSERT',
    useBatchUpdates: true,
    maxConcurrentUpdates: 10,
    maxOptimisticUpdateRetries: 5,
    optimisticUpdateRetryInterval: 50,
    updateAllProperties: false,
    metricEmissionIntervalMs: 30_000,
}

interface CacheMetrics {
    updateCacheHits: number
    updateCacheMisses: number
    checkCacheHits: number
    checkCacheMisses: number
}

class BatchWritingPersonsCache {
    private personCheckCache = new Map<string, InternalPerson | null>()
    private distinctIdToPersonId = new Map<string, string>()
    private personUpdateCache = new Map<string, PersonUpdate | null>()
    private personlessBatchResults = new Map<string, boolean>()
    private batchDistinctKeys = new Map<number, Set<string>>()
    private distinctKeyRefCount = new Map<string, number>()
    private deferredEvictions = new Set<string>()
    private pendingPrefetchesByBatchId = new Map<number, number>()
    private releasedBatchIdsWithPendingPrefetch = new Set<number>()
    private cacheMetrics: CacheMetrics = {
        updateCacheHits: 0,
        updateCacheMisses: 0,
        checkCacheHits: 0,
        checkCacheMisses: 0,
    }

    obtainForBatchId(batchId: number): BatchBoundPersonsCache {
        return new BatchBoundPersonsCache(this, batchId)
    }

    getCheckCache(): Map<string, InternalPerson | null> {
        return this.personCheckCache
    }

    getUpdateCache(): Map<string, PersonUpdate | null> {
        return this.personUpdateCache
    }

    getDistinctIdToPersonIdCache(): Map<string, string> {
        return this.distinctIdToPersonId
    }

    getPersonlessBatchResultsCache(): Map<string, boolean> {
        return this.personlessBatchResults
    }

    getBatchDistinctKeys(): Map<number, Set<string>> {
        return this.batchDistinctKeys
    }

    getDistinctKeyRefCount(): Map<string, number> {
        return this.distinctKeyRefCount
    }

    getCacheMetrics(): CacheMetrics {
        return this.cacheMetrics
    }

    resetMetrics(): void {
        this.cacheMetrics = {
            updateCacheHits: 0,
            updateCacheMisses: 0,
            checkCacheHits: 0,
            checkCacheMisses: 0,
        }
    }

    getUpdateCacheValues(): IterableIterator<PersonUpdate | null> {
        return this.personUpdateCache.values()
    }

    getUpdateCacheEntries(): IterableIterator<[string, PersonUpdate | null]> {
        return this.personUpdateCache.entries()
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        const dirtyPersonKeys = new Set<string>()
        for (const [personKey, update] of this.personUpdateCache.entries()) {
            if (update?.needs_write) {
                dirtyPersonKeys.add(personKey)
            }
        }

        const referencedBatchIds = new Set<number>()
        for (const [batchId, distinctKeys] of this.batchDistinctKeys.entries()) {
            for (const distinctKey of distinctKeys) {
                const personId = this.distinctIdToPersonId.get(distinctKey)
                if (!personId) {
                    continue
                }

                const separatorIndex = distinctKey.indexOf(':')
                const teamId = distinctKey.slice(0, separatorIndex)
                if (dirtyPersonKeys.has(`${teamId}:${personId}`)) {
                    referencedBatchIds.add(batchId)
                    break
                }
            }
        }

        return {
            dirtyEntryCount: dirtyPersonKeys.size,
            referencedBatchCount: referencedBatchIds.size,
            cacheEntryCount: this.personUpdateCache.size,
        }
    }

    getCheckCachedPerson(teamId: number, distinctId: string): InternalPerson | null | undefined {
        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)
        const result = this.personCheckCache.get(cacheKey)
        if (result !== undefined) {
            this.cacheMetrics.checkCacheHits++
            return result === null
                ? null
                : {
                      ...result,
                      properties: { ...result.properties },
                      created_at: result.created_at,
                  }
        }

        this.cacheMetrics.checkCacheMisses++
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
            if (result === null) {
                return null
            }

            return {
                ...result,
                properties: { ...result.properties },
                properties_to_set: { ...result.properties_to_set },
                properties_to_unset: [...result.properties_to_unset],
            }
        }

        this.cacheMetrics.updateCacheMisses++
        return undefined
    }

    getCachedPersonForUpdateByDistinctId(teamId: number, distinctId: string): PersonUpdate | null | undefined {
        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)
        const personId = this.distinctIdToPersonId.get(cacheKey)

        return this.getCachedPersonForUpdateByPersonId(teamId, personId)
    }

    setCachedPersonForUpdate(teamId: number, distinctId: string, person: PersonUpdate | null): void {
        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)

        if (person === null) {
            const existingPersonId = this.distinctIdToPersonId.get(cacheKey)
            this.distinctIdToPersonId.delete(cacheKey)
            if (existingPersonId) {
                this.personUpdateCache.set(this.getPersonIdCacheKey(teamId, existingPersonId), null)
            }
            return
        }

        this.distinctIdToPersonId.set(cacheKey, person.id)

        const existingPersonUpdate = this.personUpdateCache.get(this.getPersonIdCacheKey(teamId, person.id))

        if (existingPersonUpdate) {
            const mergedPersonUpdate = this.mergeUpdateIntoCachedPersonUpdate(existingPersonUpdate, person)
            this.personUpdateCache.set(this.getPersonIdCacheKey(teamId, person.id), mergedPersonUpdate)
        } else {
            this.personUpdateCache.set(this.getPersonIdCacheKey(teamId, person.id), person)
        }
    }

    setCheckCachedPerson(teamId: number, distinctId: string, person: InternalPerson | null): void {
        this.personCheckCache.set(this.getDistinctCacheKey(teamId, distinctId), person)
    }

    setDistinctIdToPersonId(teamId: number, distinctId: string, personId: string): void {
        this.distinctIdToPersonId.set(this.getDistinctCacheKey(teamId, distinctId), personId)
    }

    clearPersonCacheForPersonId(teamId: number, personId: string): void {
        this.personUpdateCache.delete(this.getPersonIdCacheKey(teamId, personId))
    }

    clearAllCachesForPersonId(teamId: number, personId: string): void {
        this.clearPersonCacheForPersonId(teamId, personId)

        const distinctIdsToRemove: string[] = []
        for (const [distinctCacheKey, mappedPersonId] of this.distinctIdToPersonId.entries()) {
            if (mappedPersonId === personId && distinctCacheKey.startsWith(`${teamId}:`)) {
                distinctIdsToRemove.push(distinctCacheKey)
            }
        }

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

        this.distinctIdToPersonId.delete(cacheKey)

        if (personId) {
            this.clearPersonCacheForPersonId(teamId, personId)
        }

        this.personCheckCache.delete(cacheKey)
    }

    setPersonlessBatchResult(teamId: number, distinctId: string, value: boolean): void {
        this.personlessBatchResults.set(this.getDistinctCacheKey(teamId, distinctId), value)
    }

    getPersonlessBatchResult(teamId: number, distinctId: string): boolean | undefined {
        return this.personlessBatchResults.get(this.getDistinctCacheKey(teamId, distinctId))
    }

    releaseBatchId(batchId: number): void {
        const keys = this.batchDistinctKeys.get(batchId)
        if (this.pendingPrefetchesByBatchId.has(batchId)) {
            this.releasedBatchIdsWithPendingPrefetch.add(batchId)
        }
        if (!keys) {
            return
        }

        for (const distinctKey of keys) {
            const refCount = (this.distinctKeyRefCount.get(distinctKey) ?? 1) - 1
            if (refCount <= 0) {
                this.distinctKeyRefCount.delete(distinctKey)
                this.evictDistinctKey(distinctKey)
            } else {
                this.distinctKeyRefCount.set(distinctKey, refCount)
            }
        }

        this.batchDistinctKeys.delete(batchId)
    }

    trackPendingPrefetch(batchIds: Set<number>): void {
        for (const batchId of batchIds) {
            this.pendingPrefetchesByBatchId.set(batchId, (this.pendingPrefetchesByBatchId.get(batchId) ?? 0) + 1)
        }
    }

    finishPendingPrefetch(batchIds: Set<number>): void {
        for (const batchId of batchIds) {
            const pendingCount = (this.pendingPrefetchesByBatchId.get(batchId) ?? 1) - 1
            if (pendingCount <= 0) {
                this.pendingPrefetchesByBatchId.delete(batchId)
                this.releasedBatchIdsWithPendingPrefetch.delete(batchId)
            } else {
                this.pendingPrefetchesByBatchId.set(batchId, pendingCount)
            }
        }
    }

    isBatchReleasedWithPendingPrefetch(batchId: number): boolean {
        return this.releasedBatchIdsWithPendingPrefetch.has(batchId)
    }

    processDeferredEvictions(): void {
        for (const distinctKey of this.deferredEvictions) {
            const colonIdx = distinctKey.indexOf(':')
            const teamId = Number(distinctKey.slice(0, colonIdx))
            const personId = this.distinctIdToPersonId.get(distinctKey)
            if (personId === undefined) {
                this.deferredEvictions.delete(distinctKey)
                continue
            }
            const personIdKey = this.getPersonIdCacheKey(teamId, personId)
            const update = this.personUpdateCache.get(personIdKey)
            if (!update || !update.needs_write) {
                this.personUpdateCache.delete(personIdKey)
                this.distinctIdToPersonId.delete(distinctKey)
                this.deferredEvictions.delete(distinctKey)
            }
        }
    }

    trackBatchEntry(batchId: number, teamId: number, distinctId: string): void {
        const distinctKey = this.getDistinctCacheKey(teamId, distinctId)
        let keys = this.batchDistinctKeys.get(batchId)
        if (!keys) {
            keys = new Set()
            this.batchDistinctKeys.set(batchId, keys)
        }
        if (!keys.has(distinctKey)) {
            keys.add(distinctKey)
            this.distinctKeyRefCount.set(distinctKey, (this.distinctKeyRefCount.get(distinctKey) ?? 0) + 1)
        }
    }

    private evictDistinctKey(distinctKey: string): void {
        const colonIdx = distinctKey.indexOf(':')
        const teamId = Number(distinctKey.slice(0, colonIdx))
        const personId = this.distinctIdToPersonId.get(distinctKey)

        if (personId !== undefined) {
            const personIdKey = this.getPersonIdCacheKey(teamId, personId)
            const update = this.personUpdateCache.get(personIdKey)
            if (!update || !update.needs_write) {
                this.personUpdateCache.delete(personIdKey)
                this.distinctIdToPersonId.delete(distinctKey)
            } else {
                this.deferredEvictions.add(distinctKey)
            }
        }

        this.personCheckCache.delete(distinctKey)
        this.personlessBatchResults.delete(distinctKey)
    }

    private mergeUpdateIntoCachedPersonUpdate(existingPersonUpdate: PersonUpdate, person: PersonUpdate): PersonUpdate {
        const mergedPersonUpdate: PersonUpdate = {
            ...existingPersonUpdate,
            properties: {
                ...existingPersonUpdate.properties,
                ...person.properties,
            },
            is_identified: existingPersonUpdate.is_identified || person.is_identified,
        }

        mergedPersonUpdate.properties_to_set = {
            ...existingPersonUpdate.properties_to_set,
            ...person.properties,
            ...person.properties_to_set,
        }
        for (const key of person.properties_to_unset) {
            delete mergedPersonUpdate.properties_to_set[key]
        }

        mergedPersonUpdate.properties_to_unset = [
            ...new Set([...existingPersonUpdate.properties_to_unset, ...person.properties_to_unset]),
        ]
        const keysToSet = new Set(Object.keys(person.properties_to_set))
        mergedPersonUpdate.properties_to_unset = mergedPersonUpdate.properties_to_unset.filter(
            (key) => !keysToSet.has(key)
        )

        mergedPersonUpdate.created_at = DateTime.min(existingPersonUpdate.created_at, person.created_at)
        mergedPersonUpdate.needs_write = existingPersonUpdate.needs_write || person.needs_write
        mergedPersonUpdate.force_update = existingPersonUpdate.force_update || person.force_update

        if (person.last_seen_at) {
            if (!mergedPersonUpdate.last_seen_at || person.last_seen_at > mergedPersonUpdate.last_seen_at) {
                mergedPersonUpdate.last_seen_at = person.last_seen_at
            }
        }

        return mergedPersonUpdate
    }

    private getDistinctCacheKey(teamId: number, distinctId: string): string {
        return `${teamId}:${distinctId}`
    }

    private getPersonIdCacheKey(teamId: number, personId: string): string {
        return `${teamId}:${personId}`
    }
}

class BatchBoundPersonsCache {
    constructor(
        private readonly cache: BatchWritingPersonsCache,
        private readonly batchId: number
    ) {}

    getCachedPersonForUpdateByDistinctId(teamId: number, distinctId: string): PersonUpdate | null | undefined {
        this.cache.trackBatchEntry(this.batchId, teamId, distinctId)
        return this.cache.getCachedPersonForUpdateByDistinctId(teamId, distinctId)
    }

    getCheckCachedPerson(teamId: number, distinctId: string): InternalPerson | null | undefined {
        this.cache.trackBatchEntry(this.batchId, teamId, distinctId)
        return this.cache.getCheckCachedPerson(teamId, distinctId)
    }

    setCachedPersonForUpdate(teamId: number, distinctId: string, person: PersonUpdate | null): void {
        this.cache.trackBatchEntry(this.batchId, teamId, distinctId)
        this.cache.setCachedPersonForUpdate(teamId, distinctId, person)
    }

    setCheckCachedPerson(teamId: number, distinctId: string, person: InternalPerson | null): void {
        this.cache.trackBatchEntry(this.batchId, teamId, distinctId)
        this.cache.setCheckCachedPerson(teamId, distinctId, person)
    }

    setDistinctIdToPersonId(teamId: number, distinctId: string, personId: string): void {
        this.cache.trackBatchEntry(this.batchId, teamId, distinctId)
        this.cache.setDistinctIdToPersonId(teamId, distinctId, personId)
    }

    setPersonlessBatchResult(teamId: number, distinctId: string, value: boolean): void {
        this.cache.trackBatchEntry(this.batchId, teamId, distinctId)
        this.cache.setPersonlessBatchResult(teamId, distinctId, value)
    }
}

/**
 * Writes persons to the database in batches, accumulating all changes for the
 * same person across events and flushing them on `flush()` calls. The cache
 * persists across batches under concurrentBatches > 1.
 *
 * **Lifecycle:** construction starts a metric-emission timer. Callers MUST
 * invoke `shutdown()` on graceful exit to stop the timer and flush any
 * remaining dirty entries.
 */
export class BatchWritingPersonsStore implements PersonsStore, BatchWritingStore {
    private personCache: BatchWritingPersonsCache
    private fetchPromisesForUpdate: Map<string, Promise<InternalPerson | null>>
    private fetchPromisesForChecking: Map<string, Promise<InternalPerson | null>>
    private methodCountsPerDistinctId: Map<string, Map<MethodName, number>>
    private databaseOperationCountsPerDistinctId: Map<string, Map<MethodName, number>>
    private updateLatencyPerDistinctIdSeconds: Map<string, Map<UpdateType, number>>
    private options: BatchWritingPersonsStoreOptions
    // Periodic metric emitter — emits accumulated per-distinct_id metrics on
    // a fixed cadence rather than at batch boundaries (which are unreliable
    // under concurrentBatches > 1).
    private metricEmissionTimer: NodeJS.Timeout | undefined

    constructor(
        private personRepository: PersonRepository,
        private ingestionWarningsOutputs: PersonOutputs,
        options?: Partial<BatchWritingPersonsStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
        this.personCache = new BatchWritingPersonsCache()
        Object.defineProperties(this, {
            personUpdateCache: { get: () => this.personCache.getUpdateCache() },
            personCheckCache: { get: () => this.personCache.getCheckCache() },
            distinctIdToPersonId: { get: () => this.personCache.getDistinctIdToPersonIdCache() },
            personlessBatchResults: { get: () => this.personCache.getPersonlessBatchResultsCache() },
            batchDistinctKeys: { get: () => this.personCache.getBatchDistinctKeys() },
            distinctKeyRefCount: { get: () => this.personCache.getDistinctKeyRefCount() },
        })
        this.fetchPromisesForUpdate = new Map()
        this.fetchPromisesForChecking = new Map()
        this.methodCountsPerDistinctId = new Map()
        this.databaseOperationCountsPerDistinctId = new Map()
        this.updateLatencyPerDistinctIdSeconds = new Map()

        if (this.options.metricEmissionIntervalMs > 0) {
            this.metricEmissionTimer = setInterval(
                () => this.emitAccumulatedMetrics(),
                this.options.metricEmissionIntervalMs
            )
            // Don't keep the process alive solely for this timer.
            this.metricEmissionTimer.unref?.()
        }
    }

    /**
     * Check if a person update should trigger a database write.
     * Returns the outcome: 'changed' (should write), 'ignored' (filtered properties only), or 'no_change' (no properties changed)
     *
     * Also tracks metrics for ignored properties at the batch level.
     */
    private getPersonUpdateOutcome(update: PersonUpdate): 'changed' | 'ignored' | 'no_change' {
        const lastSeenAtChanged =
            (update.last_seen_at?.toMillis() ?? null) !== (update.original_last_seen_at?.toMillis() ?? null)

        const hasNonPropertyChanges =
            update.is_identified !== update.original_is_identified ||
            !update.created_at.equals(update.original_created_at) ||
            lastSeenAtChanged

        if (hasNonPropertyChanges) {
            return 'changed'
        }

        const hasPropertyChanges =
            Object.keys(update.properties_to_set).length > 0 || update.properties_to_unset.length > 0

        if (!hasPropertyChanges) {
            return 'no_change'
        }

        // If force_update is set (from $identify, $set events) or updateAllProperties is enabled, bypass filtering
        if (update.force_update || this.options.updateAllProperties) {
            return 'changed'
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

            const isFiltered = isFilteredPersonUpdateProperty(key)
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

        // SYNCHRONOUS LINEARIZATION POINT for cross-batch correctness.
        // Walk every dirty entry, decide whether it needs a DB write, and
        // clear `needs_write` before any await below. Concurrent batches
        // that mutate an entry between this clear and the async DB write
        // will re-set `needs_write=true` and be picked up by the next flush.
        // DO NOT introduce any `await` inside this block.
        const updateEntries: [string, PersonUpdate][] = []
        for (const [key, update] of this.personCache.getUpdateCacheEntries()) {
            // Skip null entries - these are deleted persons or cleared cache entries
            if (!update) {
                continue
            }

            // Skip entries not marked for write - these are read-only cache entries from fetchForUpdate
            // that were cached but never modified (no events tried to update their properties)
            if (!update.needs_write) {
                continue
            }

            // Determine outcome and track metrics for this person update
            const outcome = this.getPersonUpdateOutcome(update)
            personProfileBatchUpdateOutcomeCounter.labels({ outcome }).inc()

            if (outcome === 'changed') {
                // Track which property keys caused person updates
                const metricsKeys = new Set<string>()
                Object.keys(update.properties_to_set).forEach((propertyKey) => {
                    metricsKeys.add(getMetricKey(propertyKey))
                })
                update.properties_to_unset.forEach((propertyKey) => {
                    metricsKeys.add(getMetricKey(propertyKey))
                })
                metricsKeys.forEach((propertyKey) => personPropertyKeyUpdateCounter.labels({ key: propertyKey }).inc())

                updateEntries.push([key, update])
            }

            // Clear needs_write for every dirty entry we considered, including
            // ones we decided not to write (ignored / no_change). This is the
            // linearization point — concurrent batches that mutate the entry
            // after this point will re-set needs_write=true and the next
            // flush will pick those changes up.
            update.needs_write = false
        }
        // END synchronous linearization point.

        const batchSize = updateEntries.length
        personFlushBatchSizeHistogram.observe({ db_write_mode: this.options.dbWriteMode }, batchSize)

        if (batchSize === 0) {
            personFlushLatencyHistogram.observe({ db_write_mode: this.options.dbWriteMode }, 0)
            personFlushOperationsCounter.inc({ db_write_mode: this.options.dbWriteMode, outcome: 'success' })
            this.personCache.processDeferredEvictions()
            return []
        }

        try {
            let allKafkaMessages: FlushResult[]

            switch (this.options.dbWriteMode) {
                case 'NO_ASSERT': {
                    if (this.options.useBatchUpdates) {
                        // Use batch update for NO_ASSERT mode - single query for all updates
                        allKafkaMessages = await this.flushBatchNoAssert(updateEntries)
                    } else {
                        // Use individual updates for NO_ASSERT mode
                        allKafkaMessages = await this.flushIndividualNoAssert(updateEntries)
                    }
                    break
                }
                case 'ASSERT_VERSION': {
                    // Use individual updates for ASSERT_VERSION mode (requires per-person retry logic)
                    allKafkaMessages = await this.flushIndividualAssertVersion(updateEntries)
                    break
                }
            }

            // Record successful flush
            const flushLatency = (performance.now() - flushStartTime) / 1000
            personFlushLatencyHistogram.observe({ db_write_mode: this.options.dbWriteMode }, flushLatency)
            personFlushOperationsCounter.inc({ db_write_mode: this.options.dbWriteMode, outcome: 'success' })

            this.personCache.processDeferredEvictions()
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

    getFlushStats(): BatchWritingStoreFlushStats {
        return this.personCache.getFlushStats()
    }

    /**
     * Flush all person updates using a single batch query (NO_ASSERT mode).
     * Falls back to individual updates for any persons that fail in the batch.
     */
    private async flushBatchNoAssert(updateEntries: [string, PersonUpdate][]): Promise<FlushResult[]> {
        const updates = updateEntries.map(([_, update]) => update)

        personWriteMethodAttemptCounter.inc({
            db_write_mode: this.options.dbWriteMode,
            method: 'batch',
            outcome: 'attempt',
        })

        // Try batch update first
        const batchResults = await this.personRepository.updatePersonsBatch(updates)

        const allKafkaMessages: FlushResult[] = []
        const failedUpdates: PersonUpdate[] = []

        // Process batch results
        for (const update of updates) {
            const result = batchResults.get(update.uuid)
            if (result?.success && result.kafkaMessage) {
                allKafkaMessages.push({
                    messages: [result.kafkaMessage],
                    teamId: update.team_id,
                    uuid: update.uuid,
                    distinctId: update.distinct_id,
                })
                personWriteMethodAttemptCounter.inc({
                    db_write_mode: this.options.dbWriteMode,
                    method: 'batch',
                    outcome: 'success',
                })
            } else {
                // Handle specific error types
                if (result?.error instanceof PersonPropertiesSizeViolationError) {
                    await emitIngestionWarning(
                        this.ingestionWarningsOutputs,
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
                        method: 'batch',
                        outcome: 'properties_size_violation',
                    })
                    // Don't retry size violations - they will never succeed
                    continue
                }

                // Queue for individual retry
                failedUpdates.push(update)
            }
        }

        // Fallback to individual updates for failed persons
        if (failedUpdates.length > 0) {
            logger.warn('⚠️', `Batch update had ${failedUpdates.length} failures, falling back to individual updates`, {
                failedCount: failedUpdates.length,
                totalCount: updates.length,
            })

            personFallbackOperationsCounter.inc({
                db_write_mode: this.options.dbWriteMode,
                fallback_reason: 'batch_partial_failure',
            })

            const limit = pLimit(this.options.maxConcurrentUpdates)
            const fallbackResults = await Promise.all(
                failedUpdates.map((update) =>
                    limit(async (): Promise<FlushResult[]> => {
                        try {
                            const result = await this.withMergeRetry(
                                update,
                                this.updatePersonNoAssert.bind(this),
                                'updatePersonNoAssert',
                                this.options.maxOptimisticUpdateRetries,
                                this.options.optimisticUpdateRetryInterval
                            )
                            personWriteMethodAttemptCounter.inc({
                                db_write_mode: this.options.dbWriteMode,
                                method: 'fallback',
                                outcome: 'success',
                            })
                            return [
                                {
                                    messages: result.messages,
                                    teamId: update.team_id,
                                    uuid: update.uuid,
                                    distinctId: update.distinct_id,
                                },
                            ]
                        } catch (error) {
                            return this.handleIndividualUpdateError(error, update)
                        }
                    })
                )
            )
            allKafkaMessages.push(...fallbackResults.flat())
        }

        return allKafkaMessages
    }

    /**
     * Flush all person updates using individual queries without version assertion (NO_ASSERT mode).
     * Each person is updated individually with retry logic for merge scenarios.
     */
    private async flushIndividualNoAssert(updateEntries: [string, PersonUpdate][]): Promise<FlushResult[]> {
        const limit = pLimit(this.options.maxConcurrentUpdates)

        const results = await Promise.all(
            updateEntries.map(([cacheKey, update]) =>
                limit(async (): Promise<FlushResult[]> => {
                    try {
                        personWriteMethodAttemptCounter.inc({
                            db_write_mode: this.options.dbWriteMode,
                            method: this.options.dbWriteMode,
                            outcome: 'attempt',
                        })

                        const result = await this.withMergeRetry(
                            update,
                            this.updatePersonNoAssert.bind(this),
                            'updatePersonNoAssert',
                            this.options.maxOptimisticUpdateRetries,
                            this.options.optimisticUpdateRetryInterval
                        )

                        personWriteMethodAttemptCounter.inc({
                            db_write_mode: this.options.dbWriteMode,
                            method: this.options.dbWriteMode,
                            outcome: 'success',
                        })

                        return [
                            {
                                messages: result.messages,
                                teamId: update.team_id,
                                uuid: update.uuid,
                                distinctId: update.distinct_id,
                            },
                        ]
                    } catch (error) {
                        logger.error('Failed to update person after max retries', {
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
                            method: this.options.dbWriteMode,
                            outcome: 'error',
                        })
                        return this.handleIndividualUpdateError(error, update)
                    }
                })
            )
        )

        return results.flat()
    }

    /**
     * Flush all person updates using individual queries with version assertion (ASSERT_VERSION mode).
     * This mode requires per-person retry logic for version conflicts.
     */
    private async flushIndividualAssertVersion(updateEntries: [string, PersonUpdate][]): Promise<FlushResult[]> {
        const limit = pLimit(this.options.maxConcurrentUpdates)

        const results = await Promise.all(
            updateEntries.map(([cacheKey, update]) =>
                limit(async (): Promise<FlushResult[]> => {
                    try {
                        personWriteMethodAttemptCounter.inc({
                            db_write_mode: this.options.dbWriteMode,
                            method: this.options.dbWriteMode,
                            outcome: 'attempt',
                        })

                        const result = await this.withMergeRetry(
                            update,
                            this.updatePersonAssertVersion.bind(this),
                            'updatePersonAssertVersion',
                            this.options.maxOptimisticUpdateRetries,
                            this.options.optimisticUpdateRetryInterval
                        )

                        personWriteMethodAttemptCounter.inc({
                            db_write_mode: this.options.dbWriteMode,
                            method: this.options.dbWriteMode,
                            outcome: 'success',
                        })

                        return [
                            {
                                messages: result.messages,
                                teamId: update.team_id,
                                uuid: update.uuid,
                                distinctId: update.distinct_id,
                            },
                        ]
                    } catch (error) {
                        return this.handleIndividualUpdateError(error, update)
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

        return results.flat()
    }

    /**
     * Handle errors from individual person update attempts.
     * Returns FlushResult[] for recoverable errors, throws for fatal errors.
     */
    private async handleIndividualUpdateError(error: unknown, update: PersonUpdate): Promise<FlushResult[]> {
        // If the Kafka message is too large, we can't retry, so we need to capture a warning and stop retrying
        if (error instanceof MessageSizeTooLarge) {
            await emitIngestionWarning(
                this.ingestionWarningsOutputs,
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
            await emitIngestionWarning(
                this.ingestionWarningsOutputs,
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

            return [
                {
                    messages: fallbackMessages,
                    teamId: error.latestPersonUpdate.team_id,
                    uuid: error.latestPersonUpdate.uuid,
                    distinctId: error.latestPersonUpdate.distinct_id,
                },
            ]
        }

        // Re-throw any other errors
        throw error
    }

    async inTransaction<T>(description: string, transaction: (tx: PersonsStoreTransaction) => Promise<T>): Promise<T> {
        return await this.personRepository.inTransaction(description, async (tx) => {
            const transactionWrapper = new PersonsStoreTransaction(this, tx)
            return await transaction(transactionWrapper)
        })
    }

    async fetchForChecking(teamId: Team['id'], distinctId: string, batchId: number): Promise<InternalPerson | null> {
        this.incrementCount('fetchForChecking', distinctId)
        const cache = this.personCache.obtainForBatchId(batchId)

        // First check the main cache
        const cachedPerson = cache.getCachedPersonForUpdateByDistinctId(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson === null ? null : toInternalPerson(cachedPerson)
        }

        // Then check the checking-specific cache
        const checkCachedPerson = cache.getCheckCachedPerson(teamId, distinctId)
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
                    const person = await this.personRepository.fetchPerson(teamId, distinctId, {
                        useReadReplica: true,
                        callerTag: 'ingestion/person-resolution',
                    })
                    observeLatencyByVersion(person, start, 'fetchForChecking')
                    cache.setCheckCachedPerson(teamId, distinctId, person ?? null)
                    return person ?? null
                } finally {
                    this.fetchPromisesForChecking.delete(cacheKey)
                }
            })()
            this.fetchPromisesForChecking.set(cacheKey, fetchPromise)
        } else {
            personFetchForCheckingCacheOperationsCounter.inc({ operation: 'hit' })
            cache.getCheckCachedPerson(teamId, distinctId)
        }
        return fetchPromise
    }

    /**
     * Best-effort cache warmer for the given distinct IDs. Callers fire this without awaiting it,
     * so its own rejection would become an unhandled rejection that exits the worker — so it swallows
     * transient persons-Postgres unavailability (DependencyUnavailableError) here. The failure is not
     * masked: each per-key promise (awaited by fetchForChecking/fetchForUpdate) still rejects, so a
     * consumer propagates the error and the per-distinct-id pipeline retries it. Any other error
     * (e.g. a broken query) is rethrown so it crashes loudly rather than being silently masked.
     */
    async prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void> {
        if (teamDistinctIds.length === 0) {
            return
        }

        // Filter out entries that are already cached or have pending fetches
        const uncachedEntries: { teamId: number; distinctId: string; batchId: number; cacheKey: string }[] = []

        for (const { teamId, distinctId, batchId } of teamDistinctIds) {
            const cache = this.personCache.obtainForBatchId(batchId)
            // Check if already in update cache
            const cachedPerson = cache.getCachedPersonForUpdateByDistinctId(teamId, distinctId)
            if (cachedPerson !== undefined) {
                continue
            }

            // Check if already in check cache
            const checkCachedPerson = cache.getCheckCachedPerson(teamId, distinctId)
            if (checkCachedPerson !== undefined) {
                continue
            }

            // Check if there's already a pending fetch
            const cacheKey = this.getDistinctCacheKey(teamId, distinctId)
            if (this.fetchPromisesForChecking.has(cacheKey) || this.fetchPromisesForUpdate.has(cacheKey)) {
                continue
            }

            uncachedEntries.push({ teamId, distinctId, batchId, cacheKey })
        }

        if (uncachedEntries.length === 0) {
            return
        }

        const prefetchBatchIds = new Set(uncachedEntries.map(({ batchId }) => batchId))
        this.personCache.trackPendingPrefetch(prefetchBatchIds)

        // Create a shared promise for the batch fetch that populates caches when complete
        // Use primary (useReadReplica=false) to ensure fresh data for updates
        const batchFetchPromise = this.personRepository
            .fetchPersonsByDistinctIds(
                uncachedEntries.map(({ teamId, distinctId }) => ({ teamId, distinctId })),
                false
            )
            .then((persons) => {
                // Build a map of cacheKey -> person for quick lookup
                // Strip distinct_id since InternalPerson doesn't have it
                const personsByKey = new Map<string, InternalPerson>()
                for (const person of persons) {
                    const cacheKey = this.getDistinctCacheKey(person.team_id, person.distinct_id)
                    const { distinct_id: _, ...internalPerson } = person
                    personsByKey.set(cacheKey, internalPerson)
                }

                // Cache all results (found persons and nulls for missing ones).
                for (const { teamId, distinctId, batchId, cacheKey } of uncachedEntries) {
                    if (this.personCache.isBatchReleasedWithPendingPrefetch(batchId)) {
                        continue
                    }

                    const cache = this.personCache.obtainForBatchId(batchId)
                    const person = personsByKey.get(cacheKey)
                    if (person) {
                        cache.setCheckCachedPerson(teamId, distinctId, person)
                        const personUpdate = fromInternalPerson(person, distinctId)
                        cache.setCachedPersonForUpdate(teamId, distinctId, personUpdate)
                    } else {
                        cache.setCheckCachedPerson(teamId, distinctId, null)
                    }
                }

                return personsByKey
            })
            .finally(() => {
                // Clean up the promises after completion
                for (const { cacheKey } of uncachedEntries) {
                    this.fetchPromisesForChecking.delete(cacheKey)
                }
                this.personCache.finishPendingPrefetch(prefetchBatchIds)
            })

        // Register per-key promises so fetchForChecking/fetchForUpdate can wait on the in-flight
        // batch. On failure these reject, so a consumer propagates the error (and a transient
        // DependencyUnavailableError is retried in the per-distinct-id pipeline) rather than seeing a
        // misleading "person absent" null. The throwaway catch only marks the promise handled so an
        // unconsumed key (its event may be dropped before the fetch) can't become an unhandled
        // rejection — it does not change what awaiting consumers observe.
        for (const { cacheKey } of uncachedEntries) {
            const keyPromise = batchFetchPromise.then((personsByKey) => personsByKey.get(cacheKey) ?? null)
            keyPromise.catch(() => {})
            this.fetchPromisesForChecking.set(cacheKey, keyPromise)
        }

        // Recover from a retriable failure (e.g. transient persons-Postgres unavailability) so this
        // best-effort, fire-and-forget warmer can't crash the worker. The failure is not masked:
        // consumers still observe the rejection on their per-key promise and retry it in the
        // per-distinct-id pipeline — we only swallow the redundant fire-and-forget copy. We recover
        // only on an explicit `isRetriable === true`, not the pipeline's `!== false`: an unflagged
        // error (e.g. a broken query) should rethrow and crash loudly rather than be silently masked.
        await batchFetchPromise.catch((error) => {
            if (error?.isRetriable === true) {
                logger.warn('⚠️', 'prefetchPersons failed on a retriable persons-Postgres error', {
                    error: String(error),
                })
                return
            }
            throw error
        })
    }

    async fetchForUpdate(teamId: Team['id'], distinctId: string, batchId: number): Promise<InternalPerson | null> {
        this.incrementCount('fetchForUpdate', distinctId)
        const cache = this.personCache.obtainForBatchId(batchId)

        const cachedPerson = cache.getCachedPersonForUpdateByDistinctId(teamId, distinctId)
        if (cachedPerson !== undefined) {
            return cachedPerson === null ? null : toInternalPerson(cachedPerson)
        }

        const cacheKey = this.getDistinctCacheKey(teamId, distinctId)

        // Check if there's a pending prefetch for this key - if so, wait for it to complete
        // and then return from cache (prefetch populates both caches)
        const prefetchPromise = this.fetchPromisesForChecking.get(cacheKey)
        if (prefetchPromise) {
            await prefetchPromise
            const prefetchedPerson = cache.getCachedPersonForUpdateByDistinctId(teamId, distinctId)
            if (prefetchedPerson !== undefined) {
                return prefetchedPerson === null ? null : toInternalPerson(prefetchedPerson)
            }
        }

        let fetchPromise = this.fetchPromisesForUpdate.get(cacheKey)
        if (!fetchPromise) {
            personFetchForUpdateCacheOperationsCounter.inc({ operation: 'miss' })
            fetchPromise = (async () => {
                try {
                    this.incrementDatabaseOperation('fetchForUpdate', distinctId)
                    const start = performance.now()
                    const person = await this.personRepository.fetchPerson(teamId, distinctId, {
                        useReadReplica: false,
                        callerTag: 'ingestion/person-update-conflict',
                    })
                    observeLatencyByVersion(person, start, 'fetchForUpdate')
                    if (person !== undefined) {
                        const personUpdate = fromInternalPerson(person, distinctId)
                        cache.setCachedPersonForUpdate(teamId, distinctId, personUpdate)
                        return person
                    } else {
                        // Before caching null, check if another async operation populated
                        // the cache while we were awaiting the DB query. This can happen when:
                        // 1. This operation starts DB query for a distinct ID (cache empty)
                        // 2. Another operation creates a person for that distinct ID and caches it
                        // 3. This DB query returns null (person didn't exist when query started)
                        // 4. Without this check, we would overwrite the other operation's cached person
                        //
                        // From this point, all operations are synchronous to avoid further race conditions.
                        const currentCache = cache.getCachedPersonForUpdateByDistinctId(teamId, distinctId)
                        if (currentCache === undefined) {
                            cache.setCachedPersonForUpdate(teamId, distinctId, null)
                            return null
                        }
                        return currentCache === null ? null : toInternalPerson(currentCache)
                    }
                } finally {
                    this.fetchPromisesForUpdate.delete(cacheKey)
                }
            })()
            this.fetchPromisesForUpdate.set(cacheKey, fetchPromise)
        } else {
            personFetchForUpdateCacheOperationsCounter.inc({ operation: 'hit' })
            cache.getCachedPersonForUpdateByDistinctId(teamId, distinctId)
        }
        return fetchPromise
    }

    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        batchId: number,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]>
    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]>
    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        batchIdOrTx?: number | PersonRepositoryTransaction,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        this.incrementCount('updatePersonForMerge', distinctId)
        const batchId = typeof batchIdOrTx === 'number' ? batchIdOrTx : 0
        return Promise.resolve(this.addPersonUpdateToBatch(person, update, distinctId, batchId))
    }

    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        batchId: number,
        forceUpdate?: boolean,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]>
    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        forceUpdate?: boolean,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]>
    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        batchIdOrForceUpdate?: number | boolean,
        forceUpdateOrTx?: boolean | PersonRepositoryTransaction,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        const batchId = typeof batchIdOrForceUpdate === 'number' ? batchIdOrForceUpdate : 0
        const forceUpdate =
            typeof batchIdOrForceUpdate === 'number' ? (forceUpdateOrTx as boolean | undefined) : batchIdOrForceUpdate
        const [updatedPerson, kafkaMessages] = this.addPersonPropertiesUpdateToBatch(
            person,
            propertiesToSet,
            propertiesToUnset,
            otherUpdates,
            distinctId,
            batchId,
            forceUpdate
        )
        return Promise.resolve([updatedPerson, kafkaMessages, false])
    }

    async deletePerson(
        person: InternalPerson,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<PersonMessage[]> {
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
        tx: PersonRepositoryTransaction | undefined,
        batchId: number
    ): Promise<PersonMessage[]> {
        this.incrementCount('addDistinctId', distinctId)
        this.incrementDatabaseOperation('addDistinctId', distinctId)
        const start = performance.now()
        const response = await (tx || this.personRepository).addDistinctId(person, distinctId, version)
        observeLatencyByVersion(person, start, 'addDistinctId')
        this.setDistinctIdToPersonId(person.team_id, distinctId, person.id, batchId)
        return response
    }

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction,
        batchId: number
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
            this.setCachedPersonForUpdate(target.team_id, distinctId, mergedPersonUpdate, batchId)
        } else {
            // No existing cache, create fresh cache from target person
            this.setCachedPersonForUpdate(target.team_id, distinctId, fromInternalPerson(target, distinctId), batchId)
        }
        if (response.success) {
            for (const movedDistinctId of response.distinctIdsMoved) {
                this.setDistinctIdToPersonId(target.team_id, movedDistinctId, target.id, batchId)
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

    async addPersonlessDistinctId(teamId: Team['id'], distinctId: string, batchId: number): Promise<boolean> {
        this.incrementCount('addPersonlessDistinctId', distinctId)
        const isMerged = await this.personRepository.addPersonlessDistinctId(teamId, distinctId)
        // Cache the result so later events for this distinct ID in the same batch skip the insert.
        this.personCache.obtainForBatchId(batchId).setPersonlessBatchResult(teamId, distinctId, isMerged)
        return isMerged
    }

    async addPersonlessDistinctIdForMerge(
        teamId: Team['id'],
        distinctId: string,
        tx: PersonRepositoryTransaction | undefined,
        batchId: number
    ): Promise<boolean> {
        this.incrementCount('addPersonlessDistinctIdForMerge', distinctId)
        const isMerged = await (tx || this.personRepository).addPersonlessDistinctIdForMerge(teamId, distinctId)
        // Update the batch results cache so processPersonlessStep knows this was merged
        if (isMerged) {
            this.personCache.obtainForBatchId(batchId).setPersonlessBatchResult(teamId, distinctId, true)
        }
        return isMerged
    }

    async processPersonlessDistinctIdsBatch(
        entries: { teamId: number; distinctId: string }[],
        batchId: number
    ): Promise<void> {
        if (entries.length === 0) {
            return
        }

        const cache = this.personCache.obtainForBatchId(batchId)

        const results = await this.personRepository.addPersonlessDistinctIdsBatch(entries)
        // Only store merged distinct IDs - these need force_upgrade handling.
        // Iterate entries (not result keys) to use the ':' cache key format consistently.
        for (const { teamId, distinctId } of entries) {
            if (results.get(`${teamId}|${distinctId}`)) {
                cache.setPersonlessBatchResult(teamId, distinctId, true)
            }
        }
    }

    // Returns the cached merge result for a distinct ID inserted earlier this batch:
    // true if the row was merged, false if addPersonlessDistinctId inserted it without a
    // merge, undefined if no insert was recorded. The batch and forMerge paths only cache
    // merged rows, so a non-merged insert from those paths also reads back as undefined.
    getPersonlessBatchResult(teamId: number, distinctId: string): boolean | undefined {
        return this.personCache.getPersonlessBatchResult(teamId, distinctId)
    }

    async personPropertiesSize(personId: string, teamId: number): Promise<number> {
        return await this.personRepository.personPropertiesSize(personId, teamId)
    }

    /**
     * Emit the accumulated per-distinct_id metric samples to Prometheus and
     * reset the in-memory accumulators. Runs on a fixed-interval timer in
     * production; tests may invoke it directly via `shutdown()`.
     *
     * Under concurrentBatches > 1, per-batch attribution is unreliable
     * (first-flush-wins), so emission is decoupled from batch boundaries.
     * The histogram names retain a "...PerBatch..." suffix for dashboard
     * compatibility but the window is now the emission interval.
     */
    private emitAccumulatedMetrics(): void {
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

        const cacheMetrics = this.personCache.getCacheMetrics()
        personCacheOperationsCounter.inc({ cache: 'update', operation: 'hit' }, cacheMetrics.updateCacheHits)
        personCacheOperationsCounter.inc({ cache: 'update', operation: 'miss' }, cacheMetrics.updateCacheMisses)
        personCacheOperationsCounter.inc({ cache: 'check', operation: 'hit' }, cacheMetrics.checkCacheHits)
        personCacheOperationsCounter.inc({ cache: 'check', operation: 'miss' }, cacheMetrics.checkCacheMisses)

        this.methodCountsPerDistinctId.clear()
        this.databaseOperationCountsPerDistinctId.clear()
        this.updateLatencyPerDistinctIdSeconds.clear()
        this.personCache.resetMetrics()
    }

    /**
     * Flush all dirty entries and produce the resulting Kafka messages inline.
     *
     * Convenience wrapper for callers that don't run inside the pipeline's
     * side-effect scheduler (e.g. server shutdown paths) and just need to drain
     * buffered writes synchronously. Throws on the first produce failure.
     */
    async flushAndProduceMessages(): Promise<void> {
        const flushResults = await this.flush()
        await Promise.all(
            flushResults.flatMap((record) =>
                record.messages.map((message) =>
                    this.ingestionWarningsOutputs.produce(message.output, {
                        key: null,
                        value: message.value,
                        teamId: record.teamId,
                    })
                )
            )
        )
    }

    /**
     * Stop the metric-emission timer and emit accumulated metrics. Idempotent.
     *
     * Callers MUST call `flush()` before `shutdown()`. Reaching shutdown with a
     * dirty cache indicates a drain-ordering bug — writing here without a
     * subsequent offset commit would create duplicate writes when the partition
     * is reprocessed, and silently dropping the data masks the bug. We throw
     * instead and let the caller decide whether to flush, drop, or fail loudly.
     *
     * Does NOT clear the data caches (personUpdateCache et al.). Those
     * persist for the worker's lifetime; eviction is intentionally
     * decoupled from this lifecycle hook.
     */
    shutdown(): Promise<void> {
        if (this.metricEmissionTimer) {
            clearInterval(this.metricEmissionTimer)
            this.metricEmissionTimer = undefined
        }

        const dirtyCount = Array.from(this.personCache.getUpdateCacheValues()).filter((u) => u?.needs_write).length
        if (dirtyCount > 0) {
            this.emitAccumulatedMetrics()
            throw new Error(
                `BatchWritingPersonsStore.shutdown() called with ${dirtyCount} dirty cache entries — call flush() first`
            )
        }

        this.emitAccumulatedMetrics()
        return Promise.resolve()
    }

    // Private implementation methods

    getCheckCache(): Map<string, InternalPerson | null> {
        return this.personCache.getCheckCache()
    }

    getUpdateCache(): Map<string, PersonUpdate | null> {
        return this.personCache.getUpdateCache()
    }

    private getDistinctCacheKey(teamId: number, distinctId: string): string {
        return `${teamId}:${distinctId}`
    }

    clearPersonCacheForPersonId(teamId: number, personId: string): void {
        this.personCache.clearPersonCacheForPersonId(teamId, personId)
    }

    clearAllCachesForPersonId(teamId: number, personId: string): void {
        this.personCache.clearAllCachesForPersonId(teamId, personId)
    }

    removeDistinctIdFromCache(teamId: number, distinctId: string): void {
        this.personCache.removeDistinctIdFromCache(teamId, distinctId)
    }

    clearAllCachesForDistinctId(teamId: number, distinctId: string): void {
        this.personCache.clearAllCachesForDistinctId(teamId, distinctId)
    }

    getCachedPersonForUpdateByPersonId(teamId: number, personId: string | undefined): PersonUpdate | null | undefined {
        return this.personCache.getCachedPersonForUpdateByPersonId(teamId, personId)
    }

    getCachedPersonForUpdateByDistinctId(teamId: number, distinctId: string): PersonUpdate | null | undefined {
        return this.personCache.getCachedPersonForUpdateByDistinctId(teamId, distinctId)
    }

    setCachedPersonForUpdate(teamId: number, distinctId: string, person: PersonUpdate | null, batchId?: number): void {
        this.personCache.obtainForBatchId(batchId ?? 0).setCachedPersonForUpdate(teamId, distinctId, person)
    }

    setCheckCachedPerson(teamId: number, distinctId: string, person: InternalPerson | null, batchId?: number): void {
        this.personCache.obtainForBatchId(batchId ?? 0).setCheckCachedPerson(teamId, distinctId, person)
    }

    setDistinctIdToPersonId(teamId: number, distinctId: string, personId: string, batchId?: number): void {
        this.personCache.obtainForBatchId(batchId ?? 0).setDistinctIdToPersonId(teamId, distinctId, personId)
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
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds: { distinctId: string; version?: number }[] | undefined,
        tx: PersonRepositoryTransaction | undefined,
        batchId: number
    ): Promise<CreatePersonResult> {
        this.incrementCount('createPerson', primaryDistinctId.distinctId)
        this.incrementDatabaseOperation('createPerson', primaryDistinctId.distinctId)
        const result = await (tx || this.personRepository).createPerson(
            createdAt,
            properties,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            primaryDistinctId,
            extraDistinctIds
        )

        if (result.success) {
            const { person } = result
            this.setCheckCachedPerson(teamId, primaryDistinctId.distinctId, person, batchId)
            this.setCachedPersonForUpdate(
                teamId,
                primaryDistinctId.distinctId,
                fromInternalPerson(person, primaryDistinctId.distinctId),
                batchId
            )
            for (const extraDistinctId of extraDistinctIds || []) {
                this.setDistinctIdToPersonId(teamId, extraDistinctId.distinctId, person.id, batchId)
                this.setCachedPersonForUpdate(
                    teamId,
                    extraDistinctId.distinctId,
                    fromInternalPerson(person, extraDistinctId.distinctId),
                    batchId
                )
            }
        }

        return result
    }

    private addPersonUpdateToBatch(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        batchId: number
    ): [InternalPerson, PersonMessage[], boolean] {
        const cache = this.personCache.obtainForBatchId(batchId)
        const existingUpdate = cache.getCachedPersonForUpdateByDistinctId(person.team_id, distinctId)

        let personUpdate: PersonUpdate
        if (!existingUpdate) {
            // Create new PersonUpdate from the person and apply the update
            personUpdate = fromInternalPerson(person, distinctId)
            personUpdate = this.mergeUpdateIntoPersonUpdate(personUpdate, update, true)
            personUpdate.id = person.id
            cache.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
        } else {
            // Merge updates into existing cached PersonUpdate
            personUpdate = this.mergeUpdateIntoPersonUpdate(existingUpdate, update, true)
            personUpdate.id = person.id
            cache.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
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
        distinctId: string,
        batchId: number,
        forceUpdate?: boolean
    ): [InternalPerson, PersonMessage[]] {
        const cache = this.personCache.obtainForBatchId(batchId)
        const existingUpdate = cache.getCachedPersonForUpdateByDistinctId(person.team_id, distinctId)

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

        // Handle last_seen_at - take the newer timestamp
        if (otherUpdates.last_seen_at) {
            if (!personUpdate.last_seen_at || otherUpdates.last_seen_at > personUpdate.last_seen_at) {
                personUpdate.last_seen_at = otherUpdates.last_seen_at
            }
        }

        personUpdate.needs_write = true

        // Set force_update flag with || operator - once set to true by a $identify/$set event, it stays true
        // This ensures that if any event in the batch requires forcing an update, the whole batch is written
        if (forceUpdate !== undefined) {
            personUpdate.force_update = personUpdate.force_update || forceUpdate
        }

        cache.setCachedPersonForUpdate(person.team_id, distinctId, personUpdate)
        return [toInternalPerson(personUpdate), []]
    }

    private async updatePersonNoAssert(personUpdate: PersonUpdate): Promise<PersonUpdateResult> {
        const operation = 'updatePersonNoAssert'
        this.incrementDatabaseOperation(operation as MethodName, personUpdate.distinct_id)
        // Convert PersonUpdate back to InternalPerson for database call
        const person = toInternalPerson(personUpdate)
        // Always pass all mutable fields for consistent query plans
        const updateFields = {
            properties: person.properties,
            properties_last_updated_at: person.properties_last_updated_at,
            properties_last_operation: person.properties_last_operation,
            is_identified: person.is_identified,
            created_at: person.created_at,
            last_seen_at: person.last_seen_at,
        }

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
        const latestPerson = await this.personRepository.fetchPerson(personUpdate.team_id, personUpdate.distinct_id, {
            callerTag: 'ingestion/person-version-conflict',
        })

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
     * Releases cache entries associated with the given batch ID, using reference
     * counting so entries shared across concurrent batches are only evicted when
     * all referencing batches have completed.
     */
    releaseBatch(batchId: number): void {
        this.personCache.releaseBatchId(batchId)
    }

    /**
     * Refreshes the person ID for a given distinct ID by fetching from the database.
     * This handles cases where the person was merged and the ID changed.
     * @param personUpdate the PersonUpdate that failed to update
     * @returns updated PersonUpdate with new person ID if found, null if person no longer exists
     */
    private async refreshPersonIdAfterMerge(personUpdate: PersonUpdate): Promise<PersonUpdate | null> {
        const currentPerson = await this.personRepository.fetchPerson(personUpdate.team_id, personUpdate.distinct_id, {
            callerTag: 'ingestion/person-merge-refresh',
        })

        if (!currentPerson) {
            // Person truly doesn't exist anymore
            return null
        }

        // Clear the old person ID from cache since it's been merged
        this.clearPersonCacheForPersonId(personUpdate.team_id, personUpdate.id)

        // Update our cache mapping to reflect the new person ID
        this.personCache.setDistinctIdToPersonId(personUpdate.team_id, personUpdate.distinct_id, currentPerson.id)

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
            last_seen_at: personUpdate.last_seen_at,
            needs_write: personUpdate.needs_write,
            properties_to_set: personUpdate.properties_to_set,
            properties_to_unset: personUpdate.properties_to_unset,
            original_is_identified: personUpdate.original_is_identified,
            original_created_at: personUpdate.original_created_at,
            original_last_seen_at: personUpdate.original_last_seen_at,
        }

        return updatedPersonUpdate
    }
}

/**
 * Owns a `BatchWritingPersonsStore`'s lifetime as a scope entry. `start()`
 * constructs the store (which begins its metric-emission timer); `stop()`
 * shuts it down. Shutdown throws when the cache still holds dirty entries —
 * a drain-ordering bug the pipeline's per-batch flush is supposed to prevent —
 * so we log and swallow rather than break the rest of scope teardown, matching
 * the legacy consumer's stop path.
 */
export class BatchWritingPersonsStoreComponent implements Component<BatchWritingPersonsStore> {
    constructor(
        private readonly personRepository: PersonRepository,
        private readonly outputs: PersonOutputs,
        private readonly options?: Partial<BatchWritingPersonsStoreOptions>
    ) {}

    start(): Promise<{ value: BatchWritingPersonsStore; stop: () => Promise<void> }> {
        const store = new BatchWritingPersonsStore(this.personRepository, this.outputs, this.options)
        return Promise.resolve({
            value: store,
            stop: async () => {
                try {
                    await store.shutdown()
                } catch (error) {
                    logger.error('🚨', 'BatchWritingPersonsStore.shutdown() failed', { error })
                }
            },
        })
    }
}
