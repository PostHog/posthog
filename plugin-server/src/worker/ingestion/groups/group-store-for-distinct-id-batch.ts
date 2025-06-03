import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { GroupTypeIndex, ProjectId, TeamId } from '../../../../src/types'

export interface CacheMetrics {
    cacheHits: number
    cacheMisses: number
    cacheSize: number
}

export interface GroupStoreForDistinctIdBatch {
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
