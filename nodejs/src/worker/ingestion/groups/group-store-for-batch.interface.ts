import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { GroupTypeIndex, ProjectId, TeamId } from '../../../types'
import { BatchWritingStore } from '../stores/batch-writing-store'

export interface CacheMetrics {
    cacheHits: number
    cacheMisses: number
}

export interface GroupStoreForBatch extends BatchWritingStore {
    /**
     * Reports metrics about group operations in batch
     */
    reportBatch(): void

    /**
     * Resets the batch store state, clearing all caches and metrics.
     * Should be called after flush() to prepare for the next batch.
     */
    reset(): void

    upsertGroup(
        teamId: TeamId,
        projectId: ProjectId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime
    ): Promise<void>

    getCacheMetrics(): CacheMetrics
}
