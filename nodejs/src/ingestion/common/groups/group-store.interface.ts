import { DateTime } from 'luxon'

import { GroupClickhouseMessage } from '~/common/groups/repositories/clickhouse-group-repository'
import { BatchWritingStore } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { GroupTypeIndex, ProjectId, TeamId } from '~/types'

export interface CacheMetrics {
    cacheHits: number
    cacheMisses: number
}

export type GroupFlushResult = {
    messages: GroupClickhouseMessage[]
    teamId: TeamId
    groupTypeIndex: GroupTypeIndex
    groupKey: string
}

export interface GroupStore extends BatchWritingStore<GroupFlushResult> {
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
