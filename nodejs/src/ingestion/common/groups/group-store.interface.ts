import { DateTime } from 'luxon'

import { BatchWritingStore } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { GroupTypeIndex, ProjectId, TeamId } from '~/types'

export interface CacheMetrics {
    cacheHits: number
    cacheMisses: number
}

export interface GroupStore extends BatchWritingStore {
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
    ): Promise<void>

    getCacheMetrics(): CacheMetrics
}
