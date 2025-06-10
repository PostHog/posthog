import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { GroupTypeIndex, ProjectId, TeamId } from '../../../../src/types'
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

    upsertGroup(
        teamId: TeamId,
        projectId: ProjectId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime,
        forUpdate: boolean
    ): Promise<void>

    getCacheMetrics(): CacheMetrics
}
