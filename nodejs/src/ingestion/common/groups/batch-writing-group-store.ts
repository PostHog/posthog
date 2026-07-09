import { DateTime } from 'luxon'
import pLimit from 'p-limit'

import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { GroupRepositoryTransaction } from '~/common/groups/repositories/group-repository-transaction.interface'
import { GroupRepository } from '~/common/groups/repositories/group-repository.interface'
import { GroupsOutput, IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { logger } from '~/common/utils/logger'
import { promiseRetry } from '~/common/utils/retries'
import { RaceConditionError } from '~/common/utils/utils'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { FlushResult } from '~/ingestion/common/persons/persons-store'
import { BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { GroupTypeIndex, TeamId } from '~/types'

import { logMissingRow, logVersionMismatch } from './group-logging'
import { CacheMetrics, GroupStore } from './group-store.interface'
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

    get(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): GroupUpdate | null | undefined {
        return this.cache.get(this.getCacheKey(teamId, groupTypeIndex, groupKey))
    }

    hasForBatch(batchId: number, teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): boolean {
        this.trackBatchEntry(batchId, teamId, groupTypeIndex, groupKey)
        const key = this.getCacheKey(teamId, groupTypeIndex, groupKey)
        return this.cache.has(key)
    }

    getForBatch(
        batchId: number,
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string
    ): GroupUpdate | null | undefined {
        this.trackBatchEntry(batchId, teamId, groupTypeIndex, groupKey)
        const key = this.getCacheKey(teamId, groupTypeIndex, groupKey)
        const result = this.cache.get(key)
        if (result !== undefined) {
            this.metrics.cacheHits++
        } else {
            this.metrics.cacheMisses++
        }
        return result
    }

    setForBatch(
        batchId: number,
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        group: GroupUpdate | null
    ): void {
        this.trackBatchEntry(batchId, teamId, groupTypeIndex, groupKey)
        const key = this.getCacheKey(teamId, groupTypeIndex, groupKey)
        this.cache.set(key, group)
    }

    delete(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): void {
        const key = this.getCacheKey(teamId, groupTypeIndex, groupKey)
        this.cache.delete(key)
    }

    getFetchPromise(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string
    ): Promise<GroupUpdate | null> | undefined {
        const key = this.getCacheKey(teamId, groupTypeIndex, groupKey)
        return this.fetchPromises.get(key)
    }

    setFetchPromise(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        promise: Promise<GroupUpdate | null>
    ): void {
        const key = this.getCacheKey(teamId, groupTypeIndex, groupKey)
        this.fetchPromises.set(key, promise)
    }

    deleteFetchPromise(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): void {
        const key = this.getCacheKey(teamId, groupTypeIndex, groupKey)
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
        // If a prefetch for this batch is still in flight, remember the release so the
        // prefetch's late cache writes are dropped rather than resurrecting an evicted key.
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

    // The DB unique key is (team_id, group_key, group_type_index) — the cache key must carry
    // all three, or two groups sharing a key across type indexes would alias one entry and a
    // flush could write one group's properties onto the other.
    private getCacheKey(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): string {
        return `${teamId}:${groupTypeIndex}:${groupKey}`
    }

    private trackBatchEntry(batchId: number, teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): void {
        const key = this.getCacheKey(teamId, groupTypeIndex, groupKey)
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

    has(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): boolean {
        return this.cache.hasForBatch(this.batchId, teamId, groupTypeIndex, groupKey)
    }

    get(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): GroupUpdate | null | undefined {
        return this.cache.getForBatch(this.batchId, teamId, groupTypeIndex, groupKey)
    }

    set(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string, group: GroupUpdate | null): void {
        this.cache.setForBatch(this.batchId, teamId, groupTypeIndex, groupKey, group)
    }

    getFetchPromise(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string
    ): Promise<GroupUpdate | null> | undefined {
        return this.cache.getFetchPromise(teamId, groupTypeIndex, groupKey)
    }

    setFetchPromise(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        promise: Promise<GroupUpdate | null>
    ): void {
        this.cache.setFetchPromise(teamId, groupTypeIndex, groupKey, promise)
    }

    deleteFetchPromise(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): void {
        this.cache.deleteFetchPromise(teamId, groupTypeIndex, groupKey)
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
    metricEmissionIntervalMs: 30_000,
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
    private databaseOperationCounts: Map<string, number>
    private options: BatchWritingGroupStoreOptions
    private outputs: IngestionOutputs<GroupsOutput | IngestionWarningsOutput>
    private groupRepository: GroupRepository
    private clickhouseGroupRepository: ClickhouseGroupRepository
    // Periodic metric emitter — emits accumulated group-operation metrics on
    // a fixed cadence rather than at batch boundaries.
    private metricEmissionTimer: NodeJS.Timeout | undefined

    constructor(
        outputs: IngestionOutputs<GroupsOutput | IngestionWarningsOutput>,
        groupRepository: GroupRepository,
        clickhouseGroupRepository: ClickhouseGroupRepository,
        options?: Partial<BatchWritingGroupStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
        this.groupCache = new GroupCache()
        this.databaseOperationCounts = new Map()
        this.outputs = outputs
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

    async flush(): Promise<FlushResult[]> {
        // SYNCHRONOUS LINEARIZATION POINT for cross-batch correctness.
        // Walk every dirty entry, capture it for writing, and clear
        // `needsWrite` before any await below. Concurrent batches that
        // mutate an entry between this clear and the async DB write will
        // re-set `needsWrite=true` and be picked up by the next flush.
        // DO NOT introduce any `await` inside this block.
        const pendingUpdates: [string, GroupUpdate][] = []
        for (const [key, update] of this.groupCache.entries()) {
            if (!update) {
                continue
            }
            if (!update.needsWrite) {
                continue
            }
            update.needsWrite = false
            pendingUpdates.push([key, update])
        }
        // END synchronous linearization point.

        if (pendingUpdates.length === 0) {
            this.groupCache.processDeferredEvictions()
            return []
        }

        const limit = pLimit(this.options.maxConcurrentUpdates)

        try {
            await Promise.all(
                pendingUpdates.map(([distinctId, update]) => limit(() => this.processGroupUpdate(update, distinctId)))
            )
            this.groupCache.processDeferredEvictions()
            return []
        } catch (error) {
            logger.error('Failed to flush group updates', {
                error,
                errorMessage: error instanceof Error ? error.message : String(error),
                errorStack: error instanceof Error ? error.stack : undefined,
            })
            throw error
        }
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        return this.groupCache.getFlushStats()
    }

    private async processGroupUpdate(update: GroupUpdate, distinctId: string): Promise<void> {
        try {
            await promiseRetry(
                () => this.executeOptimisticUpdate(update),
                'updateGroupOptimistically',
                this.options.maxOptimisticUpdateRetries,
                this.options.optimisticUpdateRetryInterval,
                undefined,
                [MessageSizeTooLarge]
            )
        } catch (error) {
            await this.handleOptimisticUpdateFailure(error, update, distinctId)
        }
    }

    private async handleOptimisticUpdateFailure(
        error: unknown,
        update: GroupUpdate,
        distinctId: string
    ): Promise<void> {
        if (error instanceof MessageSizeTooLarge) {
            await emitIngestionWarning(this.outputs, update.team_id, {
                type: 'group_upsert_message_size_too_large',
                details: {
                    groupTypeIndex: update.group_type_index,
                    groupKey: update.group_key,
                    distinctId: distinctId,
                },
                pipelineStep: 'group-store',
            })
            return
        }

        await this.fallbackToDirectUpsert(update, distinctId)
    }

    private async fallbackToDirectUpsert(update: GroupUpdate, distinctId: string): Promise<void> {
        logger.warn('⚠️', 'Falling back to direct upsert after max retries', {
            teamId: update.team_id,
            groupTypeIndex: update.group_type_index,
            groupKey: update.group_key,
            distinctId,
        })

        // Remove from cache to prevent retry
        this.groupCache.delete(update.team_id, update.group_type_index, update.group_key)

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

    /**
     * Best-effort cache warmer for the given group keys. Callers fire this without awaiting it,
     * so its own rejection would become an unhandled rejection that exits the worker — so it swallows
     * transient persons-Postgres unavailability (isRetriable errors) here. The failure is not masked:
     * each per-key promise (awaited by the get-or-fetch path in `getGroup`) still rejects, so a
     * consumer propagates the error and the per-distinct-id pipeline retries it. Any other error
     * (e.g. a broken query) is rethrown so it crashes loudly rather than being silently masked.
     */
    async prefetchGroups(
        entries: { teamId: TeamId; groupTypeIndex: GroupTypeIndex; groupKey: string; batchId: number }[]
    ): Promise<void> {
        if (entries.length === 0) {
            return
        }

        // Skip tuples already cached (hit or negative), with an in-flight fetch, or repeated
        // within this call. Dedup is by the full (team, type index, key) tuple — the same key
        // under two type indexes is two distinct groups and both must be fetched.
        const seen = new Set<string>()
        const uncachedEntries: {
            teamId: TeamId
            groupTypeIndex: GroupTypeIndex
            groupKey: string
            batchId: number
            cacheKey: string
        }[] = []
        for (const { teamId, groupTypeIndex, groupKey, batchId } of entries) {
            const cacheKey = `${teamId}:${groupTypeIndex}:${groupKey}`
            if (seen.has(cacheKey)) {
                continue
            }
            seen.add(cacheKey)
            const cache = this.groupCache.obtainForBatchId(batchId)
            if (cache.has(teamId, groupTypeIndex, groupKey)) {
                continue
            }
            if (cache.getFetchPromise(teamId, groupTypeIndex, groupKey)) {
                continue
            }
            uncachedEntries.push({ teamId, groupTypeIndex, groupKey, batchId, cacheKey })
        }

        if (uncachedEntries.length === 0) {
            return
        }

        const prefetchBatchIds = new Set(uncachedEntries.map(({ batchId }) => batchId))
        this.groupCache.trackPendingPrefetch(prefetchBatchIds)
        this.incrementDatabaseOperation('prefetchGroups')

        const batchFetchPromise = this.groupRepository
            .fetchGroups(
                uncachedEntries.map(({ teamId, groupTypeIndex, groupKey }) => ({ teamId, groupTypeIndex, groupKey })),
                'ingestion/group-prefetch'
            )
            .then((groups) => {
                const groupsByKey = new Map<string, GroupUpdate>()
                for (const group of groups) {
                    groupsByKey.set(`${group.team_id}:${group.group_type_index}:${group.group_key}`, fromGroup(group))
                }

                // Cache all results: found groups and negative (null) entries for misses.
                for (const { teamId, groupTypeIndex, groupKey, batchId, cacheKey } of uncachedEntries) {
                    if (this.groupCache.isBatchReleasedWithPendingPrefetch(batchId)) {
                        continue
                    }
                    const cache = this.groupCache.obtainForBatchId(batchId)
                    const groupUpdate = groupsByKey.get(cacheKey)
                    cache.set(teamId, groupTypeIndex, groupKey, groupUpdate ? { ...groupUpdate } : null)
                }

                return groupsByKey
            })
            .finally(() => {
                for (const { teamId, groupTypeIndex, groupKey } of uncachedEntries) {
                    this.groupCache.deleteFetchPromise(teamId, groupTypeIndex, groupKey)
                }
                this.groupCache.finishPendingPrefetch(prefetchBatchIds)
            })

        // Register per-key promises so the get-or-fetch path in getGroup waits on the in-flight
        // batch. On failure these reject, so a consumer propagates the error (and a transient
        // isRetriable error is retried in the per-distinct-id pipeline) rather than seeing a
        // misleading "group absent" null. The throwaway catch only marks the promise handled so an
        // unconsumed key (its event may be dropped before the fetch) can't become an unhandled
        // rejection — it does not change what awaiting consumers observe.
        for (const { teamId, groupTypeIndex, groupKey, cacheKey } of uncachedEntries) {
            const keyPromise = batchFetchPromise.then((groupsByKey) => groupsByKey.get(cacheKey) ?? null)
            keyPromise.catch(() => {})
            this.groupCache.setFetchPromise(teamId, groupTypeIndex, groupKey, keyPromise)
        }

        // Recover from a retriable failure (e.g. transient persons-Postgres unavailability) so this
        // best-effort, fire-and-forget warmer can't crash the worker. The failure is not masked:
        // consumers still observe the rejection on their per-key promise and retry it. We recover
        // only on an explicit `isRetriable === true`: an unflagged error (e.g. a broken query)
        // rethrows and crashes loudly rather than being silently masked.
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
            await this.executeGroupUpsert(
                teamId,
                groupTypeIndex,
                groupKey,
                properties,
                timestamp,
                false,
                'batch-create',
                batchId
            )
            return
        }

        const propertiesUpdate = calculateUpdate(group.group_properties || {}, properties)
        if (propertiesUpdate.updated) {
            groupCache.set(teamId, groupTypeIndex, groupKey, {
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: propertiesUpdate.properties,
                created_at: group.created_at,
                version: group.version,
                needsWrite: true,
            })
        }
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
            await this.upsertToClickhouse(
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

    private async upsertToClickhouse(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        actualVersion: number,
        source: string
    ): Promise<void> {
        this.incrementDatabaseOperation('upsertClickhouse' + (source ? `-${source}` : ''))
        await this.clickhouseGroupRepository.upsertGroup(
            teamId,
            groupTypeIndex,
            groupKey,
            properties,
            createdAt,
            actualVersion
        )
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
                groupCache?.set(teamId, groupTypeIndex, groupKey, {
                    team_id: teamId,
                    group_type_index: groupTypeIndex,
                    group_key: groupKey,
                    group_properties: propertiesUpdate.properties,
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

    private async executeOptimisticUpdate(update: GroupUpdate): Promise<void> {
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
            await this.upsertToClickhouse(
                update.team_id,
                update.group_type_index,
                update.group_key,
                update.group_properties,
                update.created_at,
                actualVersion,
                'optimistically'
            )
            return
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
            if (propertiesUpdate.updated) {
                update.group_properties = propertiesUpdate.properties
            }
            update.version = latestGroup.version
        }
        throw new Error('Optimistic update failed, will retry')
    }

    private async getGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        forUpdate: boolean,
        groupCache: BatchBoundGroupCache | undefined,
        tx?: GroupRepositoryTransaction
    ): Promise<GroupUpdate | null> {
        if (groupCache?.has(teamId, groupTypeIndex, groupKey) && !forUpdate) {
            const cachedGroup = groupCache.get(teamId, groupTypeIndex, groupKey)
            if (cachedGroup !== undefined) {
                return cachedGroup
            }
        }

        let fetchPromise = groupCache?.getFetchPromise(teamId, groupTypeIndex, groupKey)
        if (!fetchPromise) {
            groupFetchPromisesCacheOperationsCounter.inc({ operation: 'miss' })
            fetchPromise = (async () => {
                try {
                    this.incrementDatabaseOperation('fetchGroup')
                    const repository = tx || this.groupRepository
                    const existingGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey, { forUpdate })
                    if (existingGroup) {
                        const groupUpdate = fromGroup(existingGroup)
                        groupCache?.set(teamId, groupTypeIndex, groupKey, {
                            ...groupUpdate,
                            needsWrite: false,
                        })
                        return groupUpdate
                    } else {
                        groupCache?.set(teamId, groupTypeIndex, groupKey, null)
                        return null
                    }
                } finally {
                    groupCache?.deleteFetchPromise(teamId, groupTypeIndex, groupKey)
                }
            })()
            groupCache?.setFetchPromise(teamId, groupTypeIndex, groupKey, fetchPromise)
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
        if (error instanceof MessageSizeTooLarge) {
            await emitIngestionWarning(this.outputs, teamId, {
                type: 'group_upsert_message_size_too_large',
                details: {
                    groupTypeIndex,
                    groupKey,
                },
                pipelineStep: 'group-store',
            })
            return
        }
        if (error instanceof RaceConditionError) {
            // Remove from cache to prevent retry, the group was already created by another thread
            this.groupCache.delete(teamId, groupTypeIndex, groupKey)
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

        let dirtyCount = 0
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
