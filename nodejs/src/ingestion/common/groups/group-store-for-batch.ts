import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'
import { GroupTypeIndex, ProjectId, TeamId } from '~/types'

import { BatchWritingGroupStore } from './batch-writing-group-store'
import { CacheMetrics, GroupFlushResult, GroupStore } from './group-store.interface'

export type GroupStoreForBatch = Omit<GroupStore, 'upsertGroup' | 'releaseBatch' | 'getFlushStats'> & {
    upsertGroup(
        teamId: TeamId,
        projectId: ProjectId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime
    ): Promise<void>
    /**
     * Best-effort cache warmer: fetches all given group keys in one batched
     * query. Each entry may carry its own batchId for cache eviction tracking,
     * allowing a single DB fetch to service entries belonging to different
     * concurrent batches.
     */
    prefetchGroups(
        entries: { teamId: TeamId; groupTypeIndex: GroupTypeIndex; groupKey: string; batchId: number }[]
    ): Promise<void>
    readonly batchId: number
}

export class BatchBoundGroupStore implements GroupStoreForBatch {
    constructor(
        private readonly store: BatchWritingGroupStore,
        public readonly batchId: number
    ) {}

    upsertGroup(
        teamId: TeamId,
        projectId: ProjectId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime
    ): Promise<void> {
        return this.store.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, properties, timestamp, this.batchId)
    }

    prefetchGroups(
        entries: { teamId: TeamId; groupTypeIndex: GroupTypeIndex; groupKey: string; batchId: number }[]
    ): Promise<void> {
        return this.store.prefetchGroups(entries)
    }

    getCacheMetrics(): CacheMetrics {
        return this.store.getCacheMetrics()
    }

    flush(): Promise<GroupFlushResult[]> {
        return this.store.flush()
    }

    shutdown(): Promise<void> {
        return this.store.shutdown()
    }
}
