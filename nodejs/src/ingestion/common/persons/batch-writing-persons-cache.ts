import { DateTime } from 'luxon'

import { PersonUpdate } from '~/common/persons/person-update-batch'
import { BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { InternalPerson } from '~/types'

interface CacheMetrics {
    updateCacheHits: number
    updateCacheMisses: number
    checkCacheHits: number
    checkCacheMisses: number
}

export class BatchWritingPersonsCache {
    private personCheckCache = new Map<string, InternalPerson | null>()
    private distinctIdToPersonId = new Map<string, string>()
    private personUpdateCache = new Map<string, PersonUpdate | null>()
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
}
