import { DateTime } from 'luxon'
import pLimit from 'p-limit'

import {
    ClickhouseGroupRepository,
    GroupClickhouseMessage,
} from '~/common/groups/repositories/clickhouse-group-repository'
import { GroupRepositoryTransaction } from '~/common/groups/repositories/group-repository-transaction.interface'
import { GroupRepository } from '~/common/groups/repositories/group-repository.interface'
import { logger } from '~/common/utils/logger'
import { promiseRetry } from '~/common/utils/retries'
import { RaceConditionError } from '~/common/utils/utils'
import { BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { Group, GroupTypeIndex, TeamId } from '~/types'

import { logMissingRow, logVersionMismatch } from './group-logging'
import { CacheMetrics, GroupFlushResult, GroupStore } from './group-store.interface'
import { GroupUpdate, calculateUpdate, fromGroup } from './group-update'
import {
    groupCacheOperationsCounter,
    groupCacheSizeHistogram,
    groupDatabaseOperationsPerBatchHistogram,
    groupFetchPromisesCacheOperationsCounter,
    groupOptimisticUpdateConflictsPerBatchCounter,
} from './metrics'

class GroupCache {
    private cache: Map<string, GroupUpdate | null>
    private fetchPromises: Map<string, Promise<GroupUpdate | null>>
    private metrics: CacheMetrics
    private batchGroupKeys: Map<number, Set<string>>
    private groupKeyRefCount: Map<string, number>
    private deferredEvictions: Set<string>
    private pendingPrefetchesByBatchId: Map<number, number>
    private releasedBatchIdsWithPendingPrefetch: Set<number>

    constructor() {
        this.cache = new Map()
        this.fetchPromises = new Map()
        this.batchGroupKeys = new Map()
        this.groupKeyRefCount = new Map()
        this.deferredEvictions = new Set()
        this.pendingPrefetchesByBatchId = new Map()
        this.releasedBatchIdsWithPendingPrefetch = new Set()
        this.metrics = {
            cacheHits: 0,
            cacheMisses: 0,
        }
    }

    obtainForBatchId(batchId: number): BatchBoundGroupCache {
        return new BatchBoundGroupCache(this, batchId)
    }

    get(teamId: TeamId, groupKey: string): GroupUpdate | null | undefined {
        return this.cache.get(this.getCacheKey(teamId, groupKey))
    }

    hasForBatch(batchId: number, teamId: TeamId, groupKey: string): boolean {
        this.trackBatchEntry(batchId, teamId, groupKey)
        const key = this.getCacheKey(teamId, groupKey)
        return this.cache.has(key)
    }

    getForBatch(batchId: number, teamId: TeamId, groupKey: string): GroupUpdate | null | undefined {
        this.trackBatchEntry(batchId, teamId, groupKey)
        const key = this.getCacheKey(teamId, groupKey)
        const result = this.cache.get(key)
        if (result !== undefined) {
            this.metrics.cacheHits++
        } else {
            this.metrics.cacheMisses++
        }
        return result
    }

    setForBatch(batchId: number, teamId: TeamId, groupKey: string, group: GroupUpdate | null): void {
        this.trackBatchEntry(batchId, teamId, groupKey)
        const key = this.getCacheKey(teamId, groupKey)
        this.cache.set(key, group)
    }

    delete(teamId: TeamId, groupKey: string): void {
        const key = this.getCacheKey(teamId, groupKey)
        this.cache.delete(key)
    }

    getFetchPromise(teamId: TeamId, groupKey: string): Promise<GroupUpdate | null> | undefined {
        const key = this.getCacheKey(teamId, groupKey)
        return this.fetchPromises.get(key)
    }

    setFetchPromise(teamId: TeamId, groupKey: string, promise: Promise<GroupUpdate | null>): void {
        const key = this.getCacheKey(teamId, groupKey)
        this.fetchPromises.set(key, promise)
    }

    deleteFetchPromise(teamId: TeamId, groupKey: string): void {
        const key = this.getCacheKey(teamId, groupKey)
        this.fetchPromises.delete(key)
    }

    getMetrics(): CacheMetrics {
        return this.metrics
    }

    getSize(): number {
        return this.cache.size
    }

    entries(): IterableIterator<[string, GroupUpdate | null]> {
        return this.cache.entries()
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        const dirtyGroupKeys = new Set<string>()
        for (const [groupKey, update] of this.cache.entries()) {
            if (update?.needsWrite) {
                dirtyGroupKeys.add(groupKey)
            }
        }

        const referencedBatchIds = new Set<number>()
        for (const [batchId, groupKeys] of this.batchGroupKeys.entries()) {
            for (const groupKey of groupKeys) {
                if (dirtyGroupKeys.has(groupKey)) {
                    referencedBatchIds.add(batchId)
                    break
                }
            }
        }

        return {
            dirtyEntryCount: dirtyGroupKeys.size,
            referencedBatchCount: referencedBatchIds.size,
            cacheEntryCount: this.cache.size,
        }
    }

    /**
     * Reset per-batch metric accumulators. The cache and in-flight fetch
     * promises persist across batches under the persistent-cache model.
     */
    resetMetrics(): void {
        this.metrics = {
            cacheHits: 0,
            cacheMisses: 0,
        }
    }

    releaseBatchId(batchId: number): void {
        const keys = this.batchGroupKeys.get(batchId)
        if (this.pendingPrefetchesByBatchId.has(batchId)) {
            this.releasedBatchIdsWithPendingPrefetch.add(batchId)
        }
        if (!keys) {
            return
        }

        for (const groupKey of keys) {
            const refCount = (this.groupKeyRefCount.get(groupKey) ?? 1) - 1
            if (refCount <= 0) {
                this.groupKeyRefCount.delete(groupKey)
                this.evictGroupKey(groupKey)
            } else {
                this.groupKeyRefCount.set(groupKey, refCount)
            }
        }

        this.batchGroupKeys.delete(batchId)
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
        for (const groupKey of this.deferredEvictions) {
            const update = this.cache.get(groupKey)
            if (!update || !update.needsWrite) {
                this.cache.delete(groupKey)
                this.deferredEvictions.delete(groupKey)
            }
        }
    }

    private getCacheKey(teamId: TeamId, groupKey: string): string {
        return `${teamId}:${groupKey}`
    }

    private trackBatchEntry(batchId: number, teamId: TeamId, groupKey: string): void {
        const key = this.getCacheKey(teamId, groupKey)
        let keys = this.batchGroupKeys.get(batchId)
        if (!keys) {
            keys = new Set()
            this.batchGroupKeys.set(batchId, keys)
        }
        if (!keys.has(key)) {
            keys.add(key)
            this.groupKeyRefCount.set(key, (this.groupKeyRefCount.get(key) ?? 0) + 1)
        }
    }

    private evictGroupKey(groupKey: string): void {
        const update = this.cache.get(groupKey)
        if (update && update.needsWrite) {
            this.deferredEvictions.add(groupKey)
            return
        }

        this.cache.delete(groupKey)
    }
}

class BatchBoundGroupCache {
    constructor(
        private readonly cache: GroupCache,
        private readonly batchId: number
    ) {}

    has(teamId: TeamId, groupKey: string): boolean {
        return this.cache.hasForBatch(this.batchId, teamId, groupKey)
    }

    get(teamId: TeamId, groupKey: string): GroupUpdate | null | undefined {
        return this.cache.getForBatch(this.batchId, teamId, groupKey)
    }

    set(teamId: TeamId, groupKey: string, group: GroupUpdate | null): void {
        this.cache.setForBatch(this.batchId, teamId, groupKey, group)
    }

    getFetchPromise(teamId: TeamId, groupKey: string): Promise<GroupUpdate | null> | undefined {
        return this.cache.getFetchPromise(teamId, groupKey)
    }

    setFetchPromise(teamId: TeamId, groupKey: string, promise: Promise<GroupUpdate | null>): void {
        this.cache.setFetchPromise(teamId, groupKey, promise)
    }

    deleteFetchPromise(teamId: TeamId, groupKey: string): void {
        this.cache.deleteFetchPromise(teamId, groupKey)
    }
}

interface PropertiesUpdate {
    updated: boolean
    properties: Properties
}

export interface BatchWritingGroupStoreOptions {
    maxConcurrentUpdates: number
    maxOptimisticUpdateRetries: number
    optimisticUpdateRetryInterval: number
    /**
     * When true, flush writes all dirty groups in a single UNNEST statement
     * with server-side jsonb merge semantics (no version CAS, no conflict
     * retries). When false, each group is written individually with an
     * optimistic version check.
     */
    useBatchUpdates: boolean
    /**
     * Interval at which accumulated group operation metrics are emitted and
     * cleared. Set to 0 to disable the timer (used by tests; production
     * always wants a positive interval).
     */
    metricEmissionIntervalMs: number
}

const DEFAULT_OPTIONS: BatchWritingGroupStoreOptions = {
    maxConcurrentUpdates: 10,
    maxOptimisticUpdateRetries: 5,
    optimisticUpdateRetryInterval: 50,
    useBatchUpdates: false,
    metricEmissionIntervalMs: 30_000,
}

interface PendingGroupWrite {
    update: GroupUpdate
    /** Delta captured (and reset) at the flush linearization point. */
    propertiesToSet: Properties
    cacheKey: string
}

/**
 * Writes groups to the database in batches, accumulating all changes for the
 * same group across events and flushing them on `flush()` calls. The cache
 * persists across batches under concurrentBatches > 1.
 *
 * **Lifecycle:** construction starts a metric-emission timer. Callers MUST
 * invoke `shutdown()` on graceful exit to stop the timer and flush any
 * remaining dirty entries.
 */
export class BatchWritingGroupStore implements GroupStore {
    private groupCache: GroupCache
    /** ClickHouse messages queued by create/fallback paths, drained by flush(). */
    private pendingFlushResults: GroupFlushResult[] = []
    private databaseOperationCounts: Map<string, number>
    private options: BatchWritingGroupStoreOptions
    private groupRepository: GroupRepository
    private clickhouseGroupRepository: ClickhouseGroupRepository
    // Periodic metric emitter — emits accumulated group-operation metrics on
    // a fixed cadence rather than at batch boundaries.
    private metricEmissionTimer: NodeJS.Timeout | undefined

    constructor(
        groupRepository: GroupRepository,
        clickhouseGroupRepository: ClickhouseGroupRepository,
        options?: Partial<BatchWritingGroupStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
        this.groupCache = new GroupCache()
        this.databaseOperationCounts = new Map()
        this.groupRepository = groupRepository
        this.clickhouseGroupRepository = clickhouseGroupRepository

        if (this.options.metricEmissionIntervalMs > 0) {
            this.metricEmissionTimer = setInterval(
                () => this.emitAccumulatedMetrics(),
                this.options.metricEmissionIntervalMs
            )
            this.metricEmissionTimer.unref?.()
        }
    }

    getGroupCache(): GroupCache {
        return this.groupCache
    }

    async flush(): Promise<GroupFlushResult[]> {
        // SYNCHRONOUS LINEARIZATION POINT for cross-batch correctness.
        // Walk every dirty entry, capture it (and its delta) for writing, and
        // clear `needsWrite` before any await below. Concurrent batches that
        // mutate an entry between this clear and the async DB write will
        // re-set `needsWrite=true` and be picked up by the next flush.
        // DO NOT introduce any `await` inside this block.
        const pendingWrites: PendingGroupWrite[] = []
        for (const [key, update] of this.groupCache.entries()) {
            if (!update) {
                continue
            }
            if (!update.needsWrite) {
                continue
            }
            update.needsWrite = false
            const propertiesToSet = update.properties_to_set
            update.properties_to_set = {}
            pendingWrites.push({ update, propertiesToSet, cacheKey: key })
        }
        // END synchronous linearization point.

        if (pendingWrites.length === 0) {
            this.groupCache.processDeferredEvictions()
            return this.drainPendingFlushResults()
        }

        try {
            const results = this.options.useBatchUpdates
                ? await this.flushBatch(pendingWrites)
                : await this.flushIndividual(pendingWrites)
            this.groupCache.processDeferredEvictions()
            // Drained after the writes so messages queued by fallback paths
            // during this flush ride this flush's side effects too.
            return [...results, ...this.drainPendingFlushResults()]
        } catch (error) {
            logger.error('Failed to flush group updates', {
                error,
                errorMessage: error instanceof Error ? error.message : String(error),
                errorStack: error instanceof Error ? error.stack : undefined,
            })
            throw error
        }
    }

    /**
     * Write every dirty group individually with an optimistic version check.
     */
    private async flushIndividual(pendingWrites: PendingGroupWrite[]): Promise<GroupFlushResult[]> {
        const limit = pLimit(this.options.maxConcurrentUpdates)
        const results = await Promise.all(
            pendingWrites.map(({ update, cacheKey }) => limit(() => this.processGroupUpdate(update, cacheKey)))
        )
        return results.filter((result): result is GroupFlushResult => result !== null)
    }

    /**
     * Write all dirty groups in a single UNNEST statement with server-side
     * jsonb merge semantics. Groups missing from the result (deleted or never
     * created) fall back to the individual path, which creates them via the
     * direct-upsert fallback. A failure of the whole statement falls back to
     * individual optimistic writes of the full property view, so no captured
     * delta is lost.
     */
    private async flushBatch(pendingWrites: PendingGroupWrite[]): Promise<GroupFlushResult[]> {
        this.incrementDatabaseOperation('updateGroupsBatch')

        let updatedGroups: Group[]
        try {
            updatedGroups = await this.groupRepository.updateGroupsBatch(
                pendingWrites.map(({ update, propertiesToSet }) => ({
                    teamId: update.team_id,
                    groupTypeIndex: update.group_type_index,
                    groupKey: update.group_key,
                    propertiesToSet,
                    createdAt: update.created_at,
                }))
            )
        } catch (error) {
            logger.warn('⚠️', 'Batch group update failed, falling back to individual updates', {
                count: pendingWrites.length,
                error,
                errorMessage: error instanceof Error ? error.message : String(error),
            })
            return await this.flushIndividual(pendingWrites)
        }

        // Key by the full row identity — unlike the cache key, which omits
        // group_type_index — so two group types sharing a group key can never
        // sync each other's row.
        const rowIdentity = (group: { team_id: TeamId; group_type_index: GroupTypeIndex; group_key: string }) =>
            `${group.team_id}:${group.group_type_index}:${group.group_key}`
        const updatedByKey = new Map<string, Group>()
        for (const group of updatedGroups) {
            updatedByKey.set(rowIdentity(group), group)
        }

        const results: GroupFlushResult[] = []
        const missingWrites: PendingGroupWrite[] = []

        for (const pendingWrite of pendingWrites) {
            const row = updatedByKey.get(rowIdentity(pendingWrite.update))
            if (!row) {
                missingWrites.push(pendingWrite)
                continue
            }

            this.syncCacheEntryFromRow(pendingWrite.update, row)
            results.push({
                messages: [
                    this.clickhouseGroupRepository.buildUpsertMessage(
                        row.team_id,
                        row.group_type_index,
                        row.group_key,
                        row.group_properties,
                        row.created_at,
                        row.version
                    ),
                ],
                teamId: row.team_id,
                groupTypeIndex: row.group_type_index,
                groupKey: row.group_key,
            })
        }

        if (missingWrites.length > 0) {
            results.push(...(await this.flushIndividual(missingWrites)))
        }

        return results
    }

    /**
     * Sync the cached entry with the authoritative row returned by the batch
     * update, preserving any delta accumulated by concurrent batches since the
     * flush captured this write.
     */
    private syncCacheEntryFromRow(update: GroupUpdate, row: Group): void {
        const cached = this.groupCache.get(update.team_id, update.group_key)
        const target = cached ?? update
        target.group_properties = { ...row.group_properties, ...target.properties_to_set }
        target.created_at = DateTime.min(target.created_at, row.created_at)
        target.version = row.version
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        return this.groupCache.getFlushStats()
    }

    private async processGroupUpdate(update: GroupUpdate, cacheKey: string): Promise<GroupFlushResult | null> {
        try {
            const message = await promiseRetry(
                () => this.executeOptimisticUpdate(update),
                'updateGroupOptimistically',
                this.options.maxOptimisticUpdateRetries,
                // Jitter the starting interval so pods that conflicted on the
                // same group don't retry in lockstep and re-collide.
                this.options.optimisticUpdateRetryInterval * (0.5 + Math.random())
            )
            if (!message) {
                return null
            }
            return {
                messages: [message],
                teamId: update.team_id,
                groupTypeIndex: update.group_type_index,
                groupKey: update.group_key,
            }
        } catch (error) {
            await this.handleOptimisticUpdateFailure(error, update, cacheKey)
            return null
        }
    }

    private async handleOptimisticUpdateFailure(error: unknown, update: GroupUpdate, cacheKey: string): Promise<void> {
        logger.warn('⚠️', 'Optimistic group update failed after max retries', {
            error,
            teamId: update.team_id,
            groupTypeIndex: update.group_type_index,
            groupKey: update.group_key,
            cacheKey,
        })
        await this.fallbackToDirectUpsert(update, cacheKey)
    }

    private async fallbackToDirectUpsert(update: GroupUpdate, cacheKey: string): Promise<void> {
        logger.warn('⚠️', 'Falling back to direct upsert after max retries', {
            teamId: update.team_id,
            groupTypeIndex: update.group_type_index,
            groupKey: update.group_key,
            cacheKey,
        })

        // Remove from cache to prevent retry
        this.groupCache.delete(update.team_id, update.group_key)

        try {
            await this.executeGroupUpsert(
                update.team_id,
                update.group_type_index,
                update.group_key,
                update.group_properties,
                update.created_at,
                true, // forUpdate = true, making us not use the cache
                'conflictRetry',
                undefined
            )
        } catch (fallbackError) {
            logger.error('Failed to update group after max retries and direct upsert fallback', {
                error: fallbackError,
                teamId: update.team_id,
                groupTypeIndex: update.group_type_index,
                groupKey: update.group_key,
                errorMessage: fallbackError instanceof Error ? fallbackError.message : String(fallbackError),
                errorStack: fallbackError instanceof Error ? fallbackError.stack : undefined,
            })
            throw fallbackError
        }
    }

    async upsertGroup(
        teamId: TeamId,
        projectId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        batchId?: number
    ): Promise<void> {
        const effectiveBatchId = batchId ?? 0
        try {
            await this.addToBatch(teamId, groupTypeIndex, groupKey, properties, timestamp, effectiveBatchId)
        } catch (error) {
            await this.handleUpsertError(
                error,
                teamId,
                projectId,
                groupTypeIndex,
                groupKey,
                properties,
                timestamp,
                effectiveBatchId
            )
        }
    }

    private async addToBatch(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        batchId: number
    ): Promise<void> {
        const groupCache = this.groupCache.obtainForBatchId(batchId)
        const group = await this.getGroup(teamId, groupTypeIndex, groupKey, false, groupCache)

        if (!group) {
            await this.createGroup(teamId, groupTypeIndex, groupKey, properties, timestamp, batchId)
            return
        }

        const propertiesUpdate = calculateUpdate(group.group_properties || {}, properties)
        if (propertiesUpdate.updated) {
            groupCache.set(teamId, groupKey, {
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: propertiesUpdate.properties,
                // Accumulate the delta since the last DB sync — a flush in
                // flight has already captured (and reset) the previous delta.
                properties_to_set: { ...group.properties_to_set, ...propertiesUpdate.changedProperties },
                created_at: group.created_at,
                version: group.version,
                needsWrite: true,
            })
        }
    }

    /**
     * Create a group that the cache says doesn't exist. Runs without a
     * wrapping transaction — the insert is a single ON CONFLICT DO NOTHING
     * statement, so the transaction added round trips without atomicity value.
     * A racing create surfaces as RaceConditionError, which handleUpsertError
     * turns into a cache refresh and upsert retry.
     */
    private async createGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        batchId: number
    ): Promise<void> {
        const createdAt = DateTime.min(DateTime.now(), timestamp)

        this.incrementDatabaseOperation('insertGroup')
        const insertedVersion = await this.groupRepository.insertGroup(
            teamId,
            groupTypeIndex,
            groupKey,
            properties,
            createdAt,
            {},
            {}
        )

        this.groupCache.obtainForBatchId(batchId).set(teamId, groupKey, {
            team_id: teamId,
            group_type_index: groupTypeIndex,
            group_key: groupKey,
            group_properties: properties,
            properties_to_set: {},
            created_at: createdAt,
            version: insertedVersion,
            needsWrite: false,
        })

        // The ClickHouse message rides the next flush's side effects instead
        // of being awaited here: delivery reports on the downstream producer
        // can take ~seconds under backpressure, and awaiting one inline
        // serializes the per-distinct-id lane (observed in production with
        // create-heavy migration traffic).
        this.queueClickhouseMessage(
            teamId,
            groupTypeIndex,
            groupKey,
            properties,
            createdAt,
            insertedVersion,
            'batch-create'
        )
    }

    private async executeGroupUpsert(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        forUpdate: boolean,
        source: string,
        batchId?: number
    ): Promise<void> {
        const operation = 'upsertGroup' + (source ? `-${source}` : '')
        this.incrementDatabaseOperation(operation)

        const [propertiesUpdate, createdAt, actualVersion] = await this.groupRepository.inTransaction(
            operation,
            async (tx) =>
                this.executeUpsertTransaction(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    properties,
                    timestamp,
                    forUpdate,
                    tx,
                    batchId
                )
        )

        if (propertiesUpdate.updated) {
            this.queueClickhouseMessage(
                teamId,
                groupTypeIndex,
                groupKey,
                propertiesUpdate.properties,
                createdAt,
                actualVersion,
                source
            )
        }
    }

    /**
     * Queue a group's ClickHouse message for the next flush, which returns it
     * for side-effect production (awaited before the owning batch's offset
     * commit). ReplacingMergeTree ordering by version makes produce order
     * across flushes irrelevant.
     */
    private queueClickhouseMessage(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        actualVersion: number,
        source: string
    ): void {
        this.incrementDatabaseOperation('upsertClickhouse' + (source ? `-${source}` : ''))
        this.pendingFlushResults.push({
            messages: [
                this.clickhouseGroupRepository.buildUpsertMessage(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    properties,
                    createdAt,
                    actualVersion
                ),
            ],
            teamId,
            groupTypeIndex,
            groupKey,
        })
    }

    private drainPendingFlushResults(): GroupFlushResult[] {
        const pending = this.pendingFlushResults
        this.pendingFlushResults = []
        return pending
    }

    private async executeUpsertTransaction(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        forUpdate: boolean,
        tx: GroupRepositoryTransaction,
        batchId?: number
    ): Promise<[PropertiesUpdate, DateTime, number]> {
        const groupCache = batchId === undefined ? undefined : this.groupCache.obtainForBatchId(batchId)
        const group = await this.getGroup(teamId, groupTypeIndex, groupKey, forUpdate, groupCache, tx)
        const createdAt = DateTime.min(group?.created_at || DateTime.now(), timestamp)
        const expectedVersion = (group?.version || 0) + 1
        const propertiesUpdate = calculateUpdate(group?.group_properties || {}, properties)

        if (!group) {
            propertiesUpdate.updated = true
        }

        let actualVersion = expectedVersion

        if (propertiesUpdate.updated) {
            if (group) {
                actualVersion = await this.updateGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    propertiesUpdate.properties,
                    createdAt,
                    expectedVersion,
                    'upsertGroup',
                    tx
                )
            } else {
                actualVersion = await this.insertGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    propertiesUpdate.properties,
                    createdAt,
                    expectedVersion,
                    tx
                )
                groupCache?.set(teamId, groupKey, {
                    team_id: teamId,
                    group_type_index: groupTypeIndex,
                    group_key: groupKey,
                    group_properties: propertiesUpdate.properties,
                    properties_to_set: {},
                    created_at: createdAt,
                    version: actualVersion,
                    needsWrite: false,
                })
            }
        }

        return [propertiesUpdate, createdAt, actualVersion]
    }

    private async updateGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        expectedVersion: number,
        tag: string,
        tx: GroupRepositoryTransaction
    ): Promise<number> {
        this.incrementDatabaseOperation('updateGroup')
        const updatedVersion = await tx.updateGroup(
            teamId,
            groupTypeIndex,
            groupKey,
            properties,
            createdAt,
            {},
            {},
            tag
        )

        if (updatedVersion !== undefined) {
            const versionDisparity = updatedVersion - expectedVersion
            if (versionDisparity > 0) {
                logVersionMismatch(teamId, groupTypeIndex, groupKey, versionDisparity)
            }
            return updatedVersion
        } else {
            logMissingRow(teamId, groupTypeIndex, groupKey)
            return expectedVersion
        }
    }

    private async insertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        expectedVersion: number,
        tx: GroupRepositoryTransaction
    ): Promise<number> {
        this.incrementDatabaseOperation('insertGroup')
        const insertedVersion = await tx.insertGroup(teamId, groupTypeIndex, groupKey, properties, createdAt, {}, {})
        const versionDisparity = insertedVersion - expectedVersion
        if (versionDisparity > 0) {
            logVersionMismatch(teamId, groupTypeIndex, groupKey, versionDisparity)
        }
        return insertedVersion
    }

    private async executeOptimisticUpdate(update: GroupUpdate): Promise<GroupClickhouseMessage | null> {
        this.incrementDatabaseOperation('updateGroupOptimistically')
        const actualVersion = await this.groupRepository.updateGroupOptimistically(
            update.team_id,
            update.group_type_index,
            update.group_key,
            update.version,
            update.group_properties,
            update.created_at,
            {},
            {}
        )

        if (actualVersion !== undefined) {
            // Keep the cached entry's version in sync with the row we just
            // wrote, so the next flush of this entry doesn't CAS against a
            // stale version and manufacture a conflict.
            update.version = actualVersion
            // The ClickHouse produce is returned to the caller and scheduled as
            // a side effect after flush, so flush latency stays DB-only.
            return this.clickhouseGroupRepository.buildUpsertMessage(
                update.team_id,
                update.group_type_index,
                update.group_key,
                update.group_properties,
                update.created_at,
                actualVersion
            )
        }

        groupOptimisticUpdateConflictsPerBatchCounter.inc()
        this.incrementDatabaseOperation('fetchGroup')
        const latestGroup = await this.groupRepository.fetchGroup(
            update.team_id,
            update.group_type_index,
            update.group_key,
            { callerTag: 'ingestion/group-update-conflict' }
        )
        if (latestGroup) {
            const propertiesUpdate = calculateUpdate(latestGroup.group_properties || {}, update.group_properties)
            if (!propertiesUpdate.updated && update.created_at >= latestGroup.created_at) {
                // The winning writer already persisted everything this update
                // carries — common for hot groups receiving identical
                // $group_set payloads across pods. Sync to the winning row and
                // skip the write (and its ClickHouse produce) entirely.
                update.group_properties = latestGroup.group_properties || {}
                update.created_at = latestGroup.created_at
                update.version = latestGroup.version
                return null
            }
            if (propertiesUpdate.updated) {
                update.group_properties = propertiesUpdate.properties
            }
            update.version = latestGroup.version
        }
        throw new Error('Optimistic update failed, will retry')
    }

    /**
     * Best-effort cache warmer for the given group keys — one batched query
     * instead of a single-row fetch per key. Callers fire this without
     * awaiting it (mirrors prefetchPersons): transient persons-Postgres
     * unavailability is swallowed here so the fire-and-forget copy can't
     * crash the worker, while each per-key promise (awaited by getGroup)
     * still rejects so consumers propagate the error and retry. Any other
     * error is rethrown so it crashes loudly rather than being masked.
     */
    async prefetchGroups(
        entries: { teamId: TeamId; groupTypeIndex: GroupTypeIndex; groupKey: string; batchId: number }[]
    ): Promise<void> {
        if (entries.length === 0) {
            return
        }

        // Filter out entries that are already cached or have pending fetches.
        const uncachedEntries: { teamId: TeamId; groupTypeIndex: GroupTypeIndex; groupKey: string; batchId: number }[] =
            []
        const seenKeys = new Set<string>()
        for (const entry of entries) {
            const key = `${entry.teamId}:${entry.groupKey}`
            if (seenKeys.has(key)) {
                continue
            }
            seenKeys.add(key)
            if (this.groupCache.hasForBatch(entry.batchId, entry.teamId, entry.groupKey)) {
                continue
            }
            if (this.groupCache.getFetchPromise(entry.teamId, entry.groupKey)) {
                continue
            }
            uncachedEntries.push(entry)
        }

        if (uncachedEntries.length === 0) {
            return
        }

        const prefetchBatchIds = new Set(uncachedEntries.map(({ batchId }) => batchId))
        this.groupCache.trackPendingPrefetch(prefetchBatchIds)
        this.incrementDatabaseOperation('prefetchGroups')

        const batchFetchPromise = this.groupRepository
            .fetchGroupsByKeys(
                uncachedEntries.map(({ teamId }) => teamId),
                uncachedEntries.map(({ groupTypeIndex }) => groupTypeIndex),
                uncachedEntries.map(({ groupKey }) => groupKey),
                'ingestion/group-prefetch'
            )
            .then((rows) => {
                const groupsByKey = new Map<string, GroupUpdate>()
                for (const row of rows) {
                    groupsByKey.set(`${row.team_id}:${row.group_key}`, {
                        team_id: row.team_id,
                        group_type_index: row.group_type_index,
                        group_key: row.group_key,
                        group_properties: row.group_properties,
                        properties_to_set: {},
                        created_at: row.created_at,
                        version: row.version,
                        needsWrite: false,
                    })
                }

                // Cache all results (found groups and nulls for missing ones).
                for (const { teamId, groupKey, batchId } of uncachedEntries) {
                    // Caching under a released batchId would re-register it in
                    // the refcount tracking with nobody left to release it.
                    if (this.groupCache.isBatchReleasedWithPendingPrefetch(batchId)) {
                        continue
                    }
                    // Don't clobber an entry that appeared while the fetch was
                    // in flight (e.g. a group created inline by event processing).
                    if (this.groupCache.get(teamId, groupKey) !== undefined) {
                        continue
                    }
                    this.groupCache.setForBatch(
                        batchId,
                        teamId,
                        groupKey,
                        groupsByKey.get(`${teamId}:${groupKey}`) ?? null
                    )
                }

                return groupsByKey
            })
            .finally(() => {
                for (const { teamId, groupKey } of uncachedEntries) {
                    this.groupCache.deleteFetchPromise(teamId, groupKey)
                }
                this.groupCache.finishPendingPrefetch(prefetchBatchIds)
            })

        // Register per-key promises so getGroup waits on the in-flight batch
        // fetch instead of issuing its own single-row query. The throwaway
        // catch only marks the promise handled so an unconsumed key can't
        // become an unhandled rejection — awaiting consumers still observe
        // the rejection.
        for (const { teamId, groupKey } of uncachedEntries) {
            const keyPromise = batchFetchPromise.then((groupsByKey) => groupsByKey.get(`${teamId}:${groupKey}`) ?? null)
            keyPromise.catch(() => {})
            this.groupCache.setFetchPromise(teamId, groupKey, keyPromise)
        }

        await batchFetchPromise.catch((error) => {
            if (error?.isRetriable === true) {
                logger.warn('⚠️', 'prefetchGroups failed on a retriable persons-Postgres error', {
                    error: String(error),
                })
                return
            }
            throw error
        })
    }

    private async getGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        forUpdate: boolean,
        groupCache: BatchBoundGroupCache | undefined,
        tx?: GroupRepositoryTransaction
    ): Promise<GroupUpdate | null> {
        if (groupCache?.has(teamId, groupKey) && !forUpdate) {
            const cachedGroup = groupCache.get(teamId, groupKey)
            if (cachedGroup !== undefined) {
                return cachedGroup
            }
        }

        let fetchPromise = groupCache?.getFetchPromise(teamId, groupKey)
        if (!fetchPromise) {
            groupFetchPromisesCacheOperationsCounter.inc({ operation: 'miss' })
            fetchPromise = (async () => {
                try {
                    this.incrementDatabaseOperation('fetchGroup')
                    const repository = tx || this.groupRepository
                    const existingGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey, { forUpdate })
                    if (existingGroup) {
                        const groupUpdate = fromGroup(existingGroup)
                        groupCache?.set(teamId, groupKey, {
                            ...groupUpdate,
                            needsWrite: false,
                        })
                        return groupUpdate
                    } else {
                        groupCache?.set(teamId, groupKey, null)
                        return null
                    }
                } finally {
                    groupCache?.deleteFetchPromise(teamId, groupKey)
                }
            })()
            groupCache?.setFetchPromise(teamId, groupKey, fetchPromise)
        } else {
            groupFetchPromisesCacheOperationsCounter.inc({ operation: 'hit' })
        }
        return fetchPromise
    }

    private async handleUpsertError(
        error: unknown,
        teamId: TeamId,
        projectId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        batchId: number
    ): Promise<void> {
        if (error instanceof RaceConditionError) {
            // Remove from cache to prevent retry, the group was already created by another thread
            this.groupCache.delete(teamId, groupKey)
            return this.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, properties, timestamp, batchId)
        }
        throw error
    }

    releaseBatch(batchId: number): void {
        this.groupCache.releaseBatchId(batchId)
    }

    getCacheMetrics(): CacheMetrics {
        return this.groupCache.getMetrics()
    }

    private incrementDatabaseOperation(operation: string): void {
        this.databaseOperationCounts.set(operation, (this.databaseOperationCounts.get(operation) || 0) + 1)
    }

    /**
     * Emit accumulated group operation metrics to Prometheus and reset the
     * in-memory accumulators. Runs on a fixed-interval timer in production.
     *
     * Under concurrentBatches > 1, per-batch attribution is unreliable
     * (first-flush-wins), so emission is decoupled from batch boundaries.
     * The histogram names retain a "...PerBatch..." suffix for dashboard
     * compatibility but the window is now the emission interval.
     */
    private emitAccumulatedMetrics(): void {
        groupCacheSizeHistogram.observe(this.groupCache.getSize())
        const metrics = this.groupCache.getMetrics()
        groupCacheOperationsCounter.inc({ operation: 'hit' }, metrics.cacheHits)
        groupCacheOperationsCounter.inc({ operation: 'miss' }, metrics.cacheMisses)
        for (const [operation, count] of this.databaseOperationCounts.entries()) {
            groupDatabaseOperationsPerBatchHistogram.observe({ operation }, count)
        }

        this.groupCache.resetMetrics()
        this.databaseOperationCounts.clear()
        groupOptimisticUpdateConflictsPerBatchCounter.reset()
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
     * Does NOT clear the group cache. Cache eviction is intentionally
     * decoupled from this lifecycle hook.
     */
    shutdown(): Promise<void> {
        if (this.metricEmissionTimer) {
            clearInterval(this.metricEmissionTimer)
            this.metricEmissionTimer = undefined
        }

        let dirtyCount = this.pendingFlushResults.length
        for (const [_, entry] of this.groupCache.entries()) {
            if (entry && entry.needsWrite) {
                dirtyCount++
            }
        }
        if (dirtyCount > 0) {
            this.emitAccumulatedMetrics()
            throw new Error(
                `BatchWritingGroupStore.shutdown() called with ${dirtyCount} dirty cache entries — call flush() first`
            )
        }

        this.emitAccumulatedMetrics()
        return Promise.resolve()
    }
}
