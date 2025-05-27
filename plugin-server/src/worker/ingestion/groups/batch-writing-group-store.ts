import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { GroupTypeIndex, TeamId } from '../../../types'
import { DB } from '../../../utils/db/db'
import { MessageSizeTooLarge } from '../../../utils/db/error'
import { PostgresUse } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { RaceConditionError } from '../../../utils/utils'
import { captureIngestionWarning } from '../utils'
import { logMissingRow, logVersionMismatch } from './group-logging'
import { GroupStore } from './group-store'
import { GroupStoreForBatch } from './group-store-for-batch'
import { CacheMetrics, GroupStoreForDistinctIdBatch } from './group-store-for-distinct-id-batch'
import { calculateUpdate, fromGroup, GroupUpdate } from './group-update'
import { groupCacheOperationsCounter, groupCacheSizeCounter } from './metrics'

interface PropertiesUpdate {
    updated: boolean
    properties: Properties
}

export interface BatchWritingGroupStoreOptions {
    batchWritingEnabled: boolean
}

export class BatchWritingGroupStore implements GroupStore {
    constructor(
        private db: DB,
        private options: BatchWritingGroupStoreOptions = {
            batchWritingEnabled: false,
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
    }

    forDistinctID(token: string, distinctId: string): GroupStoreForDistinctIdBatch {
        const key = `${token}:${distinctId}`
        if (!this.distinctIdStores.has(key)) {
            this.distinctIdStores.set(
                key,
                new BatchWritingGroupStoreForDistinctIdBatch(this.db, this.groupCache, this.options)
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

        for (const [_, update] of this.groupCache.entries()) {
            if (!update) {
                continue
            }

            let success = false
            while (!success) {
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
                    success = true
                } else {
                    // Fetch latest version and remerge properties
                    const latestGroup = await this.db.fetchGroup(
                        update.team_id,
                        update.group_type_index,
                        update.group_key
                    )
                    if (latestGroup) {
                        // Merge our pending changes with latest DB state
                        const propertiesUpdate = calculateUpdate(
                            latestGroup.group_properties || {},
                            update.group_properties
                        )
                        if (propertiesUpdate.updated) {
                            update.group_properties = propertiesUpdate.properties
                        }
                        update.version = latestGroup.version
                    }
                }
            }

            await this.db.upsertGroupClickhouse(
                update.team_id,
                update.group_type_index,
                update.group_key,
                update.group_properties,
                update.created_at,
                update.version
            )
        }
    }

    reportBatch(): void {
        for (const store of this.distinctIdStores.values()) {
            const cacheMetrics = store.getCacheMetrics()
            groupCacheOperationsCounter.inc({ operation: 'hit' }, cacheMetrics.cacheHits)
            groupCacheOperationsCounter.inc({ operation: 'miss' }, cacheMetrics.cacheMisses)
            groupCacheSizeCounter.inc({ operation: 'size' }, cacheMetrics.cacheSize)
        }
    }
}

export class BatchWritingGroupStoreForDistinctIdBatch implements GroupStoreForDistinctIdBatch {
    private cacheMetrics: CacheMetrics
    private fetchPromises: Map<string, Promise<GroupUpdate | null>>

    constructor(
        private db: DB,
        private groupCache: Map<string, GroupUpdate | null>,
        private options: BatchWritingGroupStoreOptions = {
            batchWritingEnabled: false,
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
                await this.handleBatchUpsert(teamId, groupTypeIndex, groupKey, properties, timestamp)
            } else {
                await this.handleImmediateUpsert(teamId, groupTypeIndex, groupKey, properties, timestamp, forUpdate)
            }
        } catch (error) {
            await this.handleUpsertError(error, teamId, projectId, groupTypeIndex, groupKey, properties, timestamp)
        }
    }

    private async handleBatchUpsert(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime
    ): Promise<void> {
        const group = await this.getGroup(teamId, groupTypeIndex, groupKey, false, null)

        if (!group) {
            // For new groups, we need to insert immediately
            await this.handleImmediateUpsert(teamId, groupTypeIndex, groupKey, properties, timestamp, false)
            return
        }

        const propertiesUpdate = calculateUpdate(group.group_properties || {}, properties)
        if (propertiesUpdate.updated) {
            // Update cache with pending changes
            this.addGroupTocache(teamId, groupKey, {
                team_id: teamId,
                group_type_index: groupTypeIndex,
                group_key: groupKey,
                group_properties: propertiesUpdate.properties,
                created_at: group.created_at,
                version: group.version,
            })
        }
    }

    private async handleImmediateUpsert(
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
            async (tx) => this.handleGroupUpsert(teamId, groupTypeIndex, groupKey, properties, timestamp, forUpdate, tx)
        )

        if (propertiesUpdate.updated) {
            await this.db.upsertGroupClickhouse(teamId, groupTypeIndex, groupKey, properties, createdAt, actualVersion)
        }
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

    private addGroupTocache(teamId: TeamId, groupKey: string, group: GroupUpdate | null) {
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

        // Check cache first
        if (this.isGroupCached(teamId, groupKey)) {
            const cachedGroup = this.getCachedGroup(teamId, groupKey)
            if (cachedGroup !== undefined) {
                return cachedGroup
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
                            this.addGroupTocache(teamId, groupKey, groupUpdate)
                            this.cacheMetrics.cacheSize++
                            return groupUpdate
                        } else {
                            this.addGroupTocache(teamId, groupKey, null)
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

    private async handleGroupUpsert(
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
                actualVersion = await this.updateExistingGroup(
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
                actualVersion = await this.insertNewGroup(
                    teamId,
                    groupTypeIndex,
                    groupKey,
                    propertiesUpdate.properties,
                    createdAt,
                    expectedVersion,
                    tx
                )
                this.addGroupTocache(teamId, groupKey, {
                    team_id: teamId,
                    group_type_index: groupTypeIndex,
                    group_key: groupKey,
                    group_properties: propertiesUpdate.properties,
                    created_at: createdAt,
                    version: actualVersion,
                })
            }
        }

        return [propertiesUpdate, createdAt, actualVersion]
    }

    private async updateExistingGroup(
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

    private async insertNewGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        expectedVersion: number,
        tx: any
    ): Promise<number> {
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
}
