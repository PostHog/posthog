import { DateTime } from 'luxon'
import pLimit from 'p-limit'

import { Properties } from '@posthog/plugin-scaffold'

import { GroupTypeIndex, Hub, TeamId } from '../../../types'
import { DB } from '../../../utils/db/db'
import { MessageSizeTooLarge } from '../../../utils/db/error'
import { logger } from '../../../utils/logger'
import { promiseRetry } from '../../../utils/retries'
import { RaceConditionError } from '../../../utils/utils'
import { FlushResult } from '../persons/persons-store-for-batch'
import { captureIngestionWarning } from '../utils'
import { logMissingRow, logVersionMismatch } from './group-logging'
import { CacheMetrics, GroupStoreForBatch } from './group-store-for-batch.interface'
import { GroupStore } from './group-store.interface'
import { GroupUpdate, calculateUpdate, fromGroup } from './group-update'
import {
    groupCacheOperationsCounter,
    groupCacheSizeHistogram,
    groupDatabaseOperationsPerBatchHistogram,
    groupFetchPromisesCacheOperationsCounter,
    groupOptimisticUpdateConflictsPerBatchCounter,
} from './metrics'
import { ClickhouseGroupRepository } from './repositories/clickhouse-group-repository'
import { GroupRepositoryTransaction } from './repositories/group-repository-transaction.interface'
import { GroupRepository } from './repositories/group-repository.interface'

export type GroupHub = Pick<Hub, 'db' | 'groupRepository' | 'clickhouseGroupRepository'>

class GroupCache {
    private cache: Map<string, GroupUpdate | null>
    private fetchPromises: Map<string, Promise<GroupUpdate | null>>
    private metrics: CacheMetrics

    constructor() {
        this.cache = new Map()
        this.fetchPromises = new Map()
        this.metrics = {
            cacheHits: 0,
            cacheMisses: 0,
        }
    }

    has(teamId: TeamId, groupKey: string): boolean {
        const key = this.getCacheKey(teamId, groupKey)
        return this.cache.has(key)
    }

    get(teamId: TeamId, groupKey: string): GroupUpdate | null | undefined {
        const key = this.getCacheKey(teamId, groupKey)
        const result = this.cache.get(key)
        if (result !== undefined) {
            this.metrics.cacheHits++
        } else {
            this.metrics.cacheMisses++
        }
        return result
    }

    set(teamId: TeamId, groupKey: string, group: GroupUpdate | null): void {
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

    private getCacheKey(teamId: TeamId, groupKey: string): string {
        return `${teamId}:${groupKey}`
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
}

const DEFAULT_OPTIONS: BatchWritingGroupStoreOptions = {
    maxConcurrentUpdates: 10,
    maxOptimisticUpdateRetries: 5,
    optimisticUpdateRetryInterval: 50,
}

export class BatchWritingGroupStore implements GroupStore {
    private options: BatchWritingGroupStoreOptions

    constructor(
        private groupHub: GroupHub,
        options?: Partial<BatchWritingGroupStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
    }

    forBatch(): GroupStoreForBatch {
        return new BatchWritingGroupStoreForBatch(
            this.groupHub.db,
            this.groupHub.groupRepository,
            this.groupHub.clickhouseGroupRepository,
            this.options
        )
    }
}

/**
 * This class is used to write groups to the database in batches.
 * It will use a cache to avoid reading the same group from the database multiple times.
 * And will accumulate all changes for the same group in a single batch. At the
 * end of the batch processing, it flushes all changes to the database.
 */

export class BatchWritingGroupStoreForBatch implements GroupStoreForBatch {
    private groupCache: GroupCache
    private databaseOperationCounts: Map<string, number>
    private options: BatchWritingGroupStoreOptions

    constructor(
        private db: DB,
        private groupRepository: GroupRepository,
        private clickhouseGroupRepository: ClickhouseGroupRepository,
        options?: Partial<BatchWritingGroupStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
        this.groupCache = new GroupCache()
        this.databaseOperationCounts = new Map()
    }

    getGroupCache(): GroupCache {
        return this.groupCache
    }

    async flush(): Promise<FlushResult[]> {
        const pendingUpdates = Array.from(this.groupCache.entries()).filter((entry): entry is [string, GroupUpdate] => {
            const [_, update] = entry
            return update !== null && update.needsWrite
        })
        if (pendingUpdates.length === 0) {
            return []
        }

        const limit = pLimit(this.options.maxConcurrentUpdates)

        try {
            await Promise.all(
                pendingUpdates.map(([distinctId, update]) => limit(() => this.processGroupUpdate(update, distinctId)))
            )
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
            await captureIngestionWarning(
                this.db.kafkaProducer,
                update.team_id,
                'group_upsert_message_size_too_large',
                {
                    groupTypeIndex: update.group_type_index,
                    groupKey: update.group_key,
                }
            )
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
        this.groupCache.delete(update.team_id, update.group_key)

        try {
            await this.executeGroupUpsert(
                update.team_id,
                update.group_type_index,
                update.group_key,
                update.group_properties,
                update.created_at,
                true, // forUpdate = true, making us not use the cache
                'conflictRetry'
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
        timestamp: DateTime
    ): Promise<void> {
        try {
            await this.addToBatch(teamId, groupTypeIndex, groupKey, properties, timestamp)
        } catch (error) {
            await this.handleUpsertError(error, teamId, projectId, groupTypeIndex, groupKey, properties, timestamp)
        }
    }

    private async addToBatch(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime
    ): Promise<void> {
        const group = await this.getGroup(teamId, groupTypeIndex, groupKey, false)

        if (!group) {
            await this.executeGroupUpsert(
                teamId,
                groupTypeIndex,
                groupKey,
                properties,
                timestamp,
                false,
                'batch-create'
            )
            return
        }

        const propertiesUpdate = calculateUpdate(group.group_properties || {}, properties)
        if (propertiesUpdate.updated) {
            this.groupCache.set(teamId, groupKey, {
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
        source: string
    ): Promise<void> {
        const operation = 'upsertGroup' + (source ? `-${source}` : '')
        this.incrementDatabaseOperation(operation)

        const [propertiesUpdate, createdAt, actualVersion] = await this.groupRepository.inTransaction(
            operation,
            async (tx) =>
                this.executeUpsertTransaction(teamId, groupTypeIndex, groupKey, properties, timestamp, forUpdate, tx)
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
        tx: GroupRepositoryTransaction
    ): Promise<[PropertiesUpdate, DateTime, number]> {
        const group = await this.getGroup(teamId, groupTypeIndex, groupKey, forUpdate, tx)
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
                this.groupCache.set(teamId, groupKey, {
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
            update.group_key
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
        tx?: GroupRepositoryTransaction
    ): Promise<GroupUpdate | null> {
        if (this.groupCache.has(teamId, groupKey) && !forUpdate) {
            const cachedGroup = this.groupCache.get(teamId, groupKey)
            if (cachedGroup !== undefined) {
                return cachedGroup
            }
        }

        let fetchPromise = this.groupCache.getFetchPromise(teamId, groupKey)
        if (!fetchPromise) {
            groupFetchPromisesCacheOperationsCounter.inc({ operation: 'miss' })
            fetchPromise = (async () => {
                try {
                    this.incrementDatabaseOperation('fetchGroup')
                    const repository = tx || this.groupRepository
                    const existingGroup = await repository.fetchGroup(teamId, groupTypeIndex, groupKey, { forUpdate })
                    if (existingGroup) {
                        const groupUpdate = fromGroup(existingGroup)
                        this.groupCache.set(teamId, groupKey, {
                            ...groupUpdate,
                            needsWrite: false,
                        })
                        return groupUpdate
                    } else {
                        this.groupCache.set(teamId, groupKey, null)
                        return null
                    }
                } finally {
                    this.groupCache.deleteFetchPromise(teamId, groupKey)
                }
            })()
            this.groupCache.setFetchPromise(teamId, groupKey, fetchPromise)
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
        timestamp: DateTime
    ): Promise<void> {
        if (error instanceof MessageSizeTooLarge) {
            await captureIngestionWarning(this.db.kafkaProducer, teamId, 'group_upsert_message_size_too_large', {
                groupTypeIndex,
                groupKey,
            })
            return
        }
        if (error instanceof RaceConditionError) {
            // Remove from cache to prevent retry, the group was already created by another thread
            this.groupCache.delete(teamId, groupKey)
            return this.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, properties, timestamp)
        }
        throw error
    }

    getCacheMetrics(): CacheMetrics {
        return this.groupCache.getMetrics()
    }

    private incrementDatabaseOperation(operation: string): void {
        this.databaseOperationCounts.set(operation, (this.databaseOperationCounts.get(operation) || 0) + 1)
    }

    reportBatch(): void {
        groupCacheSizeHistogram.observe(this.groupCache.getSize())
        const metrics = this.groupCache.getMetrics()
        groupCacheOperationsCounter.inc({ operation: 'hit' }, metrics.cacheHits)
        groupCacheOperationsCounter.inc({ operation: 'miss' }, metrics.cacheMisses)
        for (const [operation, count] of this.databaseOperationCounts.entries()) {
            groupDatabaseOperationsPerBatchHistogram.observe({ operation }, count)
        }
    }
}
