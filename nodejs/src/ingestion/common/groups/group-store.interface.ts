import { DateTime } from 'luxon'

import { BatchWritingStore } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { GroupTypeIndex, ProjectId, TeamId } from '~/types'

export interface CacheMetrics {
    cacheHits: number
    cacheMisses: number
}

/**
 * The group store defers its ClickHouse group produces so they run off the
 * per-event hot path. Both `upsertGroup` (inline create) and `flush` (batched
 * updates) return the produce promises for the caller to attach as pipeline
 * side effects; those side effects are awaited before the consumer commits
 * offsets, preserving the at-least-once envelope.
 */
export interface GroupStore extends BatchWritingStore<Promise<unknown>> {
    /**
     * Stop any background work (e.g., periodic metric emission) and flush
     * remaining accumulated metrics. Called on graceful shutdown. Does NOT
     * clear data caches.
     */
    shutdown(): Promise<void>

    upsertGroup(
        teamId: TeamId,
        projectId: ProjectId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        batchId: number
    ): Promise<Promise<unknown>[]>

    getCacheMetrics(): CacheMetrics
}
