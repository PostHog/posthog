import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import pLimit from 'p-limit'

import { GroupTypeIndex, TeamId } from '../../../types'
import { DB } from '../../../utils/db/db'
import { MessageSizeTooLarge } from '../../../utils/db/error'
import { PostgresUse } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { promiseRetry } from '../../../utils/retries'
import { RaceConditionError } from '../../../utils/utils'
import { captureIngestionWarning } from '../utils'
import { logMissingRow, logVersionMismatch } from './group-logging'
import { GroupStore } from './group-store'
import { GroupStoreForBatch } from './group-store-for-batch'
import { CacheMetrics, GroupStoreForDistinctIdBatch } from './group-store-for-distinct-id-batch'
import { calculateUpdate, fromGroup, GroupUpdate } from './group-update'
import {
    groupCacheOperationsCounter,
    groupCacheSizeGauge,
    groupDatabaseOperationsPerBatchHistogram,
    groupOptimisticUpdateConflictsPerBatchCounter,
} from './metrics'

interface PropertiesUpdate {
    updated: boolean
    properties: Properties
}

export interface BatchWritingGroupStoreOptions {
    batchWritingEnabled: boolean
    maxConcurrentUpdates: number
}

export class BatchWritingGroupStore implements GroupStore {
    constructor(
        private db: DB,
        private options: BatchWritingGroupStoreOptions = {
            batchWritingEnabled: false,
            maxConcurrentUpdates: 10,
        }
    ) {}

    forBatch(): GroupStoreForBatch {
        return new BatchWritingGroupStoreForBatch(this.db, this.options)
    }
}

/**
 * This class is used to write groups to the database in batches.
 * It will use a cache to avoid reading the same group from the database multiple times.
 * And will accumulate all changes for the same group in a single batch. At the
 * end of the batch processing, it flushes all changes to the database.
 */

export class BatchWritingGroupStoreForBatch implements GroupStoreForBatch {
    private distinctIdStores: Map<string, BatchWritingGroupStoreForDistinctIdBatch>
    private databaseOperationCounts: Map<string, number>
    /**
     * A cache of groups that have been read from the database.
     *
     * This is used to avoid reading the same group from the database multiple times.
     * Within a batch, we will retrieve the group data from the database and fill the cache
     * and then use the cache for subsequent operations.
     * This cache is shared between all BatchWritingGroupStoreForDistinctIdBatch
     *
     * Cache data is flushed to Postgres after the batch is complete, if batch writing is enabled.
     *
     */
    private groupCache: Map<string, GroupUpdate | null>

    constructor(private db: DB, private options: BatchWritingGroupStoreOptions) {
        this.distinctIdStores = new Map()
        this.groupCache = new Map()
        this.databaseOperationCounts = new Map()
    }

    forDistinctID(token: string, distinctId: string): GroupStoreForDistinctIdBatch {
        const key = `${token}:${distinctId}`
        if (!this.distinctIdStores.has(key)) {
            this.distinctIdStores.set(
                key,
                new BatchWritingGroupStoreForDistinctIdBatch(
                    this.db,
                    this.groupCache,
                    this.databaseOperationCounts,
                    this.options
                )
            )
        } else {
            logger.warn('⚠️', 'Reusing existing persons store for distinct ID in batch', { token, distinctId })
        }
        return this.distinctIdStores.get(key)!
    }

    async flush(): Promise<void> {
        if (!this.options.batchWritingEnabled) {
            return
        }

        const limit = pLimit(this.options.maxConcurrentUpdates)
        const updates = Array.from(this.groupCache.entries())
            .filter(([_, update]) => update !== null && update.needsWrite)
            .map(([_, update]) => update!)

        await Promise.all(
            updates.map((update) =>
                limit(async () => {
                    try {
                        await promiseRetry(
                            () => this.updateGroupOptimistically(update),
                            'updateGroupOptimistically',
                            3, // max retries
                            1000 // initial retry interval
                        )
                    } catch (error) {
                        logger.error('Failed to update group after max retries', {
                            error,
                            teamId: update.team_id,
                            groupTypeIndex: update.group_type_index,
                            groupKey: update.group_key,
                        })
                    }
                })
            )
        )
    }

    private async updateGroupOptimistically(update: GroupUpdate): Promise<void> {
        this.incrementDatabaseOperation('updateGroupOptimistically')
        const actualVersion = await this.db.updateGroupOptimistically(
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
            await this.db.upsertGroupClickhouse(
                update.team_id,
                update.group_type_index,
                update.group_key,
                update.group_properties,
                update.created_at,
                actualVersion
            )
            return
        }

        groupOptimisticUpdateConflictsPerBatchCounter.inc()
        // Fetch latest version and remerge properties
        this.incrementDatabaseOperation('fetchGroup')
        const latestGroup = await this.db.fetchGroup(update.team_id, update.group_type_index, update.group_key)
        if (latestGroup) {
            // Merge our pending changes with latest DB state
            const propertiesUpdate = calculateUpdate(latestGroup.group_properties || {}, update.group_properties)
            if (propertiesUpdate.updated) {
                update.group_properties = propertiesUpdate.properties
            }
            update.version = latestGroup.version
        }
        throw new Error('Optimistic update failed, will retry')
    }

    private incrementDatabaseOperation(operation: string): void {
        this.databaseOperationCounts.set(operation, (this.databaseOperationCounts.get(operation) || 0) + 1)
    }

    reportBatch(): void {
        for (const store of this.distinctIdStores.values()) {
            const cacheMetrics = store.getCacheMetrics()
            groupCacheOperationsCounter.inc({ operation: 'hit' }, cacheMetrics.cacheHits)
            groupCacheOperationsCounter.inc({ operation: 'miss' }, cacheMetrics.cacheMisses)
            groupCacheSizeGauge.observe(cacheMetrics.cacheSize)
        }
        for (const [operation, count] of this.databaseOperationCounts.entries()) {
            groupDatabaseOperationsPerBatchHistogram.observe({ operation }, count)
        }
    }
}

export class BatchWritingGroupStoreForDistinctIdBatch implements GroupStoreForDistinctIdBatch {
    private cacheMetrics: CacheMetrics
    private fetchPromises: Map<string, Promise<GroupUpdate | null>>

    constructor(
        private db: DB,
        private groupCache: Map<string, GroupUpdate | null>,
        private databaseOperationCounts: Map<string, number>,
        private options: BatchWritingGroupStoreOptions = {
            batchWritingEnabled: false,
            maxConcurrentUpdates: 10,
        }
    ) {
        this.fetchPromises = new Map()
        this.cacheMetrics = {
            cacheHits: 0,
            cacheMisses: 0,
            cacheSize: 0,
        }
    }

    async upsertGroup(
        teamId: TeamId,
        projectId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        forUpdate: boolean = true
    ): Promise<void> {
        try {
            if (this.options.batchWritingEnabled) {
                await this.addGroupUpsertToBatch(teamId, groupTypeIndex, groupKey, properties, timestamp)
            } else {
                await this.upsertGroupDirectly(teamId, groupTypeIndex, groupKey, properties, timestamp, forUpdate)
            }
        } catch (error) {
            await this.handleUpsertError(error, teamId, projectId, groupTypeIndex, groupKey, properties, timestamp)
        }
    }

    private async addGroupUpsertToBatch(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime
    ): Promise<void> {
        const group = await this.getGroup(teamId, groupTypeIndex, groupKey, false, null)

        if (!group) {
            // For new groups, we need to insert immediately
            await this.upsertGroupDirectly(teamId, groupTypeIndex, groupKey, properties, timestamp, false)
            return
        }

        const propertiesUpdate = calculateUpdate(group.group_properties || {}, properties)
        if (propertiesUpdate.updated) {
            // Update cache with pending changes
            this.addGroupToCache(teamId, groupKey, {
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

    private async upsertGroupDirectly(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        forUpdate: boolean
    ): Promise<void> {
        const [propertiesUpdate, createdAt, actualVersion] = await this.db.postgres.transaction(
            PostgresUse.COMMON_WRITE,
            'upsertGroup',
            async (tx) =>
                this.groupUpsertTransaction(teamId, groupTypeIndex, groupKey, properties, timestamp, forUpdate, tx)
        )

        if (propertiesUpdate.updated) {
            await this.db.upsertGroupClickhouse(
                teamId,
                groupTypeIndex,
                groupKey,
                propertiesUpdate.properties,
                createdAt,
                actualVersion
            )
        }
    }

    private async groupUpsertTransaction(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        forUpdate: boolean,
        tx: any
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
                this.addGroupToCache(teamId, groupKey, {
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
        tx: any
    ): Promise<number> {
        const updatedVersion = await this.db.updateGroup(
            teamId,
            groupTypeIndex,
            groupKey,
            properties,
            createdAt,
            {},
            {},
            tag,
            tx
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
        tx: any
    ): Promise<number> {
        this.incrementDatabaseOperation('insertGroup')
        const insertedVersion = await this.db.insertGroup(
            teamId,
            groupTypeIndex,
            groupKey,
            properties,
            createdAt,
            {},
            {},
            tx
        )
        const versionDisparity = insertedVersion - expectedVersion
        if (versionDisparity > 0) {
            logVersionMismatch(teamId, groupTypeIndex, groupKey, versionDisparity)
        }
        return insertedVersion
    }

    private isGroupCached(teamId: TeamId, groupKey: string) {
        const key = this.getCacheKey(teamId, groupKey)
        return this.groupCache.has(key)
    }

    private getCachedGroup(teamId: TeamId, groupKey: string): GroupUpdate | null | undefined {
        const key = this.getCacheKey(teamId, groupKey)
        const result = this.groupCache.get(key)
        if (result !== undefined) {
            this.cacheMetrics.cacheHits++
        } else {
            this.cacheMetrics.cacheMisses++
        }
        return result
    }

    private addGroupToCache(teamId: TeamId, groupKey: string, group: GroupUpdate | null) {
        const key = this.getCacheKey(teamId, groupKey)
        this.groupCache.set(key, group)
    }

    private async getGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        forUpdate: boolean,
        tx: any
    ): Promise<GroupUpdate | null> {
        const cacheKey = this.getCacheKey(teamId, groupKey)

        if (this.options.batchWritingEnabled) {
            // Check cache first
            if (this.isGroupCached(teamId, groupKey)) {
                const cachedGroup = this.getCachedGroup(teamId, groupKey)
                if (cachedGroup !== undefined) {
                    return cachedGroup
                }
            }
        }

        // Check if there's an ongoing fetch for this group
        let fetchPromise = this.fetchPromises.get(cacheKey)
        if (!fetchPromise) {
            fetchPromise = (async () => {
                try {
                    const existingGroup = await this.db.fetchGroup(teamId, groupTypeIndex, groupKey, tx, { forUpdate })
                    if (this.options.batchWritingEnabled) {
                        if (existingGroup) {
                            const groupUpdate = fromGroup(existingGroup)
                            this.addGroupToCache(teamId, groupKey, {
                                ...groupUpdate,
                                needsWrite: true,
                            })
                            this.cacheMetrics.cacheSize++
                            return groupUpdate
                        } else {
                            this.addGroupToCache(teamId, groupKey, null)
                            this.cacheMetrics.cacheSize++
                            return null
                        }
                    }
                    return existingGroup ? fromGroup(existingGroup) : null
                } finally {
                    this.fetchPromises.delete(cacheKey)
                }
            })()
            this.fetchPromises.set(cacheKey, fetchPromise)
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
            return this.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, properties, timestamp)
        }
        throw error
    }

    getCacheMetrics(): CacheMetrics {
        return this.cacheMetrics
    }

    private getCacheKey(teamId: number, groupKey: string): string {
        return `${teamId}:${groupKey}`
    }

    private incrementDatabaseOperation(operation: string): void {
        this.databaseOperationCounts.set(operation, (this.databaseOperationCounts.get(operation) || 0) + 1)
    }
}
