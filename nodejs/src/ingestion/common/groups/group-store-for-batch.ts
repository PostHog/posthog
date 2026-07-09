import { DateTime } from 'luxon'

import { FlushResult } from '~/ingestion/common/persons/persons-store'
import { Properties } from '~/plugin-scaffold'
import { GroupTypeIndex, ProjectId, TeamId } from '~/types'

import { BatchWritingGroupStore } from './batch-writing-group-store'
import { CacheMetrics, GroupStore } from './group-store.interface'

export type GroupStoreForBatch = Omit<GroupStore, 'upsertGroup' | 'releaseBatch' | 'getFlushStats'> & {
    upsertGroup(
        teamId: TeamId,
        projectId: ProjectId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        timestamp: DateTime
    ): Promise<void>
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

    flush(): Promise<FlushResult[]> {
        return this.store.flush()
    }

    shutdown(): Promise<void> {
        return this.store.shutdown()
    }
}
