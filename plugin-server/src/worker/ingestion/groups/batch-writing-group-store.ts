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
import { CacheMetrics, GroupStoreForBatch } from './group-store-for-batch'
import { calculateUpdate, fromGroup, GroupUpdate } from './group-update'
import {
    groupCacheOperationsCounter,
    groupCacheSizeHistogram,
    groupDatabaseOperationsPerBatchHistogram,
    groupFetchPromisesCacheOperationsCounter,
    groupOptimisticUpdateConflictsPerBatchCounter,
} from './metrics'

interface PropertiesUpdate {
    updated: boolean
    properties: Properties
}

export interface BatchWritingGroupStoreOptions {
    batchWritingEnabled: boolean
    maxConcurrentUpdates: number
    maxOptimisticUpdateRetries: number
    optimisticUpdateRetryInterval: number
}

const DEFAULT_OPTIONS: BatchWritingGroupStoreOptions = {
    batchWritingEnabled: false,
    maxConcurrentUpdates: 10,
    maxOptimisticUpdateRetries: 5,
    optimisticUpdateRetryInterval: 50,
}

export class BatchWritingGroupStore implements GroupStore {
    private options: BatchWritingGroupStoreOptions

    constructor(private db: DB, options?: Partial<BatchWritingGroupStoreOptions>) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
    }

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
    private groupCache: Map<string, GroupUpdate | null>
    private databaseOperationCounts: Map<string, number>
    private fetchPromises: Map<string, Promise<GroupUpdate | null>>
    private cacheMetrics: CacheMetrics
    private options: BatchWritingGroupStoreOptions

    constructor(private db: DB, options?: Partial<BatchWritingGroupStoreOptions>) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
        this.groupCache = new Map()
        this.databaseOperationCounts = new Map()
        this.fetchPromises = new Map()
        this.cacheMetrics = {
            cacheHits: 0,
            cacheMisses: 0,
        }
    }

    async flush(): Promise<void> {
        if (!this.options.batchWritingEnabled) {
            return
        }

        const limit = pLimit(this.options.maxConcurrentUpdates)

        await Promise.all(
            Array.from(this.groupCache.entries())
                .filter((entry): entry is [string, GroupUpdate] => {
                    const [_, update] = entry
                    return update !== null && update.needsWrite
                })
                .map(([distinctId, update]) =>
                    limit(async () => {
                        try {
                            await promiseRetry(
                                () => this.updateGroupOptimistically(update),
                                'updateGroupOptimistically',
                                this.options.maxOptimisticUpdateRetries,
                                this.options.optimisticUpdateRetryInterval,
                                undefined,
                                [MessageSizeTooLarge]
                            )
                        } catch (error) {
                            // If the Kafka message is too large, we can't retry, so we need to capture a warning and stop retrying
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
                            logger.warn('⚠️', 'Falling back to direct upsert after max retries', {
                                teamId: update.team_id,
                                groupTypeIndex: update.group_type_index,
                                groupKey: update.group_key,
                            })
                            // Remove the group from the cache, so we don't try to update it again
                            this.groupCache.delete(this.getCacheKey(update.team_id, update.group_key))
                            await this.upsertGroupDirectly(
                                update.team_id,
                                update.group_type_index,
                                update.group_key,
                                update.group_properties,
                                update.created_at,
                                true, // forUpdate = true, making us not use the cache
                                'conflictRetry'
                            )
                        }
                    }).catch((error) => {
                        logger.error('Failed to update group after max retries and direct upsert fallback', {
                            error,
                            distinctId,
                            teamId: update.team_id,
                            groupTypeIndex: update.group_type_index,
                            groupKey: update.group_key,
                            errorMessage: error instanceof Error ? error.message : String(error),
                            errorStack: error instanceof Error ? error.stack : undefined,
                        })
                        throw error
                    })
                )
        ).catch((error) => {
            logger.error('Failed to flush group updates', {
                error,
                errorMessage: error instanceof Error ? error.message : String(error),
                errorStack: error instanceof Error ? error.stack : undefined,
            })
            throw error
        })
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
                await this.upsertGroupDirectly(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    properties,
                    timestamp,
                    forUpdate,
                    'upsertGroup'
                )
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
            await this.upsertGroupDirectly(
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

        logger.info('👥', 'adding group to batch, group already exists', {
            teamId,
            groupTypeIndex,
            groupKey,
        })

        const propertiesUpdate = calculateUpdate(group.group_properties || {}, properties)
        if (propertiesUpdate.updated) {
            logger.info('👥', 'adding group to batch, group properties updated', {
                teamId,
                groupTypeIndex,
                groupKey,
            })
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
        forUpdate: boolean,
        source: string
    ): Promise<void> {
        const operation = 'upsertGroup' + (source ? `-${source}` : '')
        this.incrementDatabaseOperation(operation)
        const [propertiesUpdate, createdAt, actualVersion] = await this.db.postgres.transaction(
            PostgresUse.PERSONS_WRITE,
            operation,
            async (tx) =>
                this.groupUpsertTransaction(teamId, groupTypeIndex, groupKey, properties, timestamp, forUpdate, tx)
        )

        if (propertiesUpdate.updated) {
            this.incrementDatabaseOperation('upsertGroupClickhouse' + (source ? `-${source}` : ''))
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
                if (this.options.batchWritingEnabled) {
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
        this.incrementDatabaseOperation('updateGroup')
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
            this.incrementDatabaseOperation('upsertGroupClickhouse-updateGroupOptimistically')
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
        this.incrementDatabaseOperation('fetchGroup')
        const latestGroup = await this.db.fetchGroup(update.team_id, update.group_type_index, update.group_key)
        if (latestGroup) {
            const propertiesUpdate = calculateUpdate(latestGroup.group_properties || {}, update.group_properties)
            if (propertiesUpdate.updated) {
                update.group_properties = propertiesUpdate.properties
            }
            update.version = latestGroup.version
        }
        throw new Error('Optimistic update failed, will retry')
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

        if (this.isGroupCached(teamId, groupKey) && !forUpdate) {
            const cachedGroup = this.getCachedGroup(teamId, groupKey)
            if (cachedGroup !== undefined) {
                return cachedGroup
            }
        }

        let fetchPromise = this.fetchPromises.get(cacheKey)
        if (!fetchPromise) {
            groupFetchPromisesCacheOperationsCounter.inc({ operation: 'miss' })
            fetchPromise = (async () => {
                try {
                    this.incrementDatabaseOperation('fetchGroup')
                    const existingGroup = await this.db.fetchGroup(teamId, groupTypeIndex, groupKey, tx, { forUpdate })
                    if (this.options.batchWritingEnabled) {
                        if (existingGroup) {
                            const groupUpdate = fromGroup(existingGroup)
                            this.addGroupToCache(teamId, groupKey, {
                                ...groupUpdate,
                                needsWrite: false,
                            })
                            return groupUpdate
                        } else {
                            this.addGroupToCache(teamId, groupKey, null)
                            return null
                        }
                    }
                    return existingGroup ? fromGroup(existingGroup) : null
                } finally {
                    this.fetchPromises.delete(cacheKey)
                }
            })()
            this.fetchPromises.set(cacheKey, fetchPromise)
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

    reportBatch(): void {
        groupCacheSizeHistogram.observe(this.groupCache.size)
        groupCacheOperationsCounter.inc({ operation: 'hit' }, this.cacheMetrics.cacheHits)
        groupCacheOperationsCounter.inc({ operation: 'miss' }, this.cacheMetrics.cacheMisses)
        for (const [operation, count] of this.databaseOperationCounts.entries()) {
            groupDatabaseOperationsPerBatchHistogram.observe({ operation }, count)
        }
    }
}
