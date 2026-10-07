import { isEqual } from 'lodash'
import { DateTime } from 'luxon'

import { PendingLanes, PersonUpdate } from '~/common/persons/person-update-batch'
import { BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { InternalPerson } from '~/types'

interface CacheMetrics {
    updateCacheHits: number
    updateCacheMisses: number
    checkCacheHits: number
    checkCacheMisses: number
}

type PendingChange = { set: unknown } | { setOnce: unknown } | { unset: true }
type Lanes = PendingLanes

function emptyLanes(): Lanes {
    return { properties_to_set: {}, properties_to_set_once: {}, properties_to_unset: [] }
}

/** One key's pending change, tagged by lane, so two records compare by what each would send. */
function pendingChangeFor(update: Lanes, name: string): PendingChange | undefined {
    if (Object.hasOwn(update.properties_to_set, name)) {
        return { set: update.properties_to_set[name] }
    }
    if (Object.hasOwn(update.properties_to_set_once, name)) {
        return { setOnce: update.properties_to_set_once[name] }
    }
    if (update.properties_to_unset.includes(name)) {
        return { unset: true }
    }
    return undefined
}

/**
 * Removes from the entry, pending lanes and write out alike, each change equal to the one a write or a merge
 * carried for that key; a differing change made since stays.
 */
export function retireCarried(entry: PersonUpdate, carried: Lanes): void {
    const names = new Set([
        ...Object.keys(carried.properties_to_set),
        ...Object.keys(carried.properties_to_set_once),
        ...carried.properties_to_unset,
    ])
    const held = entry.in_flight ? [entry, entry.in_flight.lanes] : [entry]
    for (const name of names) {
        const landed = pendingChangeFor(carried, name)
        for (const lanes of held) {
            const pending = pendingChangeFor(lanes, name)
            if (pending !== undefined && !isEqual(pending, landed)) {
                continue
            }
            delete lanes.properties_to_set[name]
            delete lanes.properties_to_set_once[name]
            lanes.properties_to_unset = lanes.properties_to_unset.filter((unset) => unset !== name)
        }
    }
}

/** Later lanes win over earlier ones: a key set later is no longer unset, and one unset later is no longer set. */
function mergeLanes(earlier: Lanes, later: Lanes): Lanes {
    const properties_to_set = { ...earlier.properties_to_set, ...later.properties_to_set }
    const properties_to_set_once = { ...earlier.properties_to_set_once }
    // A set-once over an earlier unset of its key applies unconditionally, as the segment fold resolves it: the
    // unset guarantees the key is absent when the set-once lands.
    for (const [key, value] of Object.entries(later.properties_to_set_once)) {
        if (earlier.properties_to_unset.includes(key) && !Object.hasOwn(later.properties_to_set, key)) {
            properties_to_set[key] = value
        } else {
            properties_to_set_once[key] = value
        }
    }
    for (const key of later.properties_to_unset) {
        delete properties_to_set[key]
        delete properties_to_set_once[key]
    }
    const setLater = new Set([...Object.keys(later.properties_to_set), ...Object.keys(later.properties_to_set_once)])
    const properties_to_unset = [
        ...new Set([...earlier.properties_to_unset.filter((key) => !setLater.has(key)), ...later.properties_to_unset]),
    ]
    return { properties_to_set, properties_to_set_once, properties_to_unset }
}

/**
 * Takes the pending lanes as the entry's one write out and marks the scalars as judged, so the next decision
 * weighs only what arrives afterwards. The flush decides no entry with a write out until that write has answered.
 */
export function beginWrite(entry: PersonUpdate, settled: Promise<void>): void {
    entry.in_flight = {
        lanes: {
            properties_to_set: entry.properties_to_set,
            properties_to_set_once: entry.properties_to_set_once,
            properties_to_unset: entry.properties_to_unset,
        },
        originals: {
            original_is_identified: entry.original_is_identified,
            original_created_at: entry.original_created_at,
            original_last_seen_at: entry.original_last_seen_at,
        },
        version: entry.version,
        force: entry.force_update ?? false,
        settled,
    }
    entry.properties_to_set = {}
    entry.properties_to_set_once = {}
    entry.properties_to_unset = []
    entry.original_is_identified = entry.is_identified
    entry.original_created_at = entry.created_at
    entry.original_last_seen_at = entry.last_seen_at
}

/**
 * Hands the write out back to pending when no answer can say whether it landed, so the next event's flush decision
 * weighs it again if one arrives before the batch's release; otherwise the lanes leave with the entry, as pending
 * lanes always have. A newer pending change for a key keeps precedence, and the force it judged with comes back.
 */
export function returnWrite(entry: PersonUpdate): void {
    const write = entry.in_flight
    if (!write) {
        return
    }
    entry.in_flight = undefined
    const pending = mergeLanes(write.lanes, entry)
    entry.properties_to_set = pending.properties_to_set
    entry.properties_to_set_once = pending.properties_to_set_once
    entry.properties_to_unset = pending.properties_to_unset
    // The originals belong to the base the decision judged from. A newer row taken since carries its own, which
    // still show the unlanded scalar change, so they stay.
    if (entry.version === write.version) {
        Object.assign(entry, write.originals)
    }
    entry.force_update = entry.force_update || write.force
}

/** A copy of everything the entry still holds for the row, the write out and pending, the pending lanes winning. */
export function heldLanes(entry: PersonUpdate): Lanes {
    return mergeLanes(entry.in_flight?.lanes ?? emptyLanes(), entry)
}

export function holdsChanges(entry: PersonUpdate): boolean {
    return entry.in_flight !== undefined || hasLanes(entry)
}

type RowScalars = Pick<InternalPerson, 'properties' | 'is_identified' | 'created_at' | 'last_seen_at'>

/**
 * Points the entry's base at a row newer than the one it reflects, scalars included, so a flush with no newer
 * change stays a no-op; a change made since the snapshot keeps precedence the way the statement merges it.
 */
export function takeRow(entry: PersonUpdate, row: RowScalars, version: number): void {
    entry.version = version
    entry.properties = { ...row.properties }
    entry.is_identified = entry.is_identified || row.is_identified
    entry.created_at = DateTime.min(entry.created_at, row.created_at)
    if (row.last_seen_at && (!entry.last_seen_at || row.last_seen_at > entry.last_seen_at)) {
        entry.last_seen_at = row.last_seen_at
    }
    entry.original_is_identified = row.is_identified
    entry.original_created_at = row.created_at
    entry.original_last_seen_at = row.last_seen_at
}

function hasLanes(lanes: Lanes): boolean {
    return (
        Object.keys(lanes.properties_to_set).length > 0 ||
        Object.keys(lanes.properties_to_set_once).length > 0 ||
        lanes.properties_to_unset.length > 0
    )
}

/**
 * An entry nothing holds: no change waits for a flush and no write is out. One with a write out stays until the
 * answer lands or hands the write back; a re-target after a merge needs it as the carrier.
 */
function idle(update: PersonUpdate | null | undefined): boolean {
    return !update || (!update.needs_write && !update.in_flight)
}

export class BatchWritingPersonsCache {
    private personCheckCache = new Map<string, InternalPerson | null>()
    /**
     * Counts entry drops while row reads are in flight. A read that began before a person's entry was dropped
     * may have read the row before whatever dropped it, so its answer is not installed for that person.
     */
    private generation = 0
    private droppedAt = new Map<string, number>()
    private readsInFlight = new Map<number, number>()
    private nextRead = 0
    private distinctIdToPersonId = new Map<string, string>()
    private personUpdateCache = new Map<string, PersonUpdate | null>()
    private batchDistinctKeys = new Map<number, Set<string>>()
    private distinctKeyRefCount = new Map<string, number>()
    private deferredEvictions = new Set<string>()
    /** Entries kept without distinct ids for a flush to re-target, by person key; evicted once clean. */
    private detachedEntries = new Set<string>()
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
                properties_to_set_once: { ...result.properties_to_set_once },
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
                const personIdKey = this.getPersonIdCacheKey(teamId, existingPersonId)
                this.dropEntry(personIdKey)
                this.personUpdateCache.set(personIdKey, null)
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
        this.dropEntry(this.getPersonIdCacheKey(teamId, personId))
    }

    clearAllCachesForPersonId(teamId: number, personId: string): void {
        this.clearPersonCacheForPersonId(teamId, personId)
        this.dropDistinctIdsForPersonId(teamId, personId)
    }

    /** Sends the next read of each of the person's distinct ids to the row; the entry itself stays. */
    private dropDistinctIdsForPersonId(teamId: number, personId: string): void {
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
        for (const personIdKey of this.detachedEntries) {
            if (idle(this.personUpdateCache.get(personIdKey))) {
                this.dropEntry(personIdKey)
                this.detachedEntries.delete(personIdKey)
            }
        }
        for (const distinctKey of this.deferredEvictions) {
            const colonIdx = distinctKey.indexOf(':')
            const teamId = Number(distinctKey.slice(0, colonIdx))
            const personId = this.distinctIdToPersonId.get(distinctKey)
            if (personId === undefined) {
                this.deferredEvictions.delete(distinctKey)
                continue
            }
            const personIdKey = this.getPersonIdCacheKey(teamId, personId)
            if (idle(this.personUpdateCache.get(personIdKey))) {
                this.dropEntry(personIdKey)
                this.distinctIdToPersonId.delete(distinctKey)
                this.deferredEvictions.delete(distinctKey)
            }
        }
    }

    /** The uuid of the person a distinct id maps to, from its live entry; undefined when the id is not mapped. */
    uuidFor(teamId: number, distinctId: string): string | undefined {
        const personId = this.distinctIdToPersonId.get(this.getDistinctCacheKey(teamId, distinctId))
        if (personId === undefined) {
            return undefined
        }
        return this.personUpdateCache.get(this.getPersonIdCacheKey(teamId, personId))?.uuid
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
            if (idle(this.personUpdateCache.get(personIdKey))) {
                this.dropEntry(personIdKey)
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
            is_identified: existingPersonUpdate.is_identified || person.is_identified,
        }
        // A row read replaces the base only when it is newer than the row the base reflects; an older read, or an
        // entry built from this one or its view, carries no newer version and leaves it.
        if (person.version > existingPersonUpdate.version) {
            takeRow(
                mergedPersonUpdate,
                {
                    properties: person.properties,
                    is_identified: person.original_is_identified,
                    created_at: person.original_created_at,
                    last_seen_at: person.original_last_seen_at,
                },
                person.version
            )
        }

        // Pending holds only this pod's sets, never the fetched row; the later record's lanes win.
        const lanes = mergeLanes(existingPersonUpdate, person)
        mergedPersonUpdate.properties_to_set = lanes.properties_to_set
        mergedPersonUpdate.properties_to_set_once = lanes.properties_to_set_once
        mergedPersonUpdate.properties_to_unset = lanes.properties_to_unset

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

    beginRead(): number {
        const read = this.nextRead++
        this.readsInFlight.set(read, this.generation)
        return read
    }

    endRead(read: number): void {
        this.readsInFlight.delete(read)
        if (this.readsInFlight.size === 0) {
            this.droppedAt.clear()
        } else if (this.droppedAt.size > 256) {
            const oldest = Math.min(...this.readsInFlight.values())
            for (const [key, at] of this.droppedAt) {
                if (at <= oldest) {
                    this.droppedAt.delete(key)
                }
            }
        }
    }

    droppedSince(teamId: number, personId: string, read: number): boolean {
        const began = this.readsInFlight.get(read) ?? this.generation
        return (this.droppedAt.get(this.getPersonIdCacheKey(teamId, personId)) ?? -1) > began
    }

    private dropEntry(personIdKey: string): void {
        this.personUpdateCache.delete(personIdKey)
        this.fenceReads(personIdKey)
    }

    /** A read that began before now does not install this person, whether or not its entry stays. */
    private fenceReads(personIdKey: string): void {
        if (this.readsInFlight.size > 0) {
            this.droppedAt.set(personIdKey, ++this.generation)
        }
    }

    /**
     * Keeps the entry for the next flush alone: its distinct ids read the row, a read from before now does not
     * reinstall the person, and the entry is evicted once it is clean.
     */
    detachEntry(teamId: number, personId: string): void {
        const personIdKey = this.getPersonIdCacheKey(teamId, personId)
        this.fenceReads(personIdKey)
        this.dropDistinctIdsForPersonId(teamId, personId)
        this.detachedEntries.add(personIdKey)
    }

    /** The live entry itself: no copy and no cache hit metrics. */
    getLiveUpdate(teamId: number, personId: string): PersonUpdate | null | undefined {
        return this.personUpdateCache.get(this.getPersonIdCacheKey(teamId, personId))
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
