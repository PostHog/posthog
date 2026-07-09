import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { sanitizeString } from '~/common/utils/db/utils'
import { GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { GroupTypeIndex, ProjectId, Team } from '~/types'

type PrefetchGroupsStepInput = { event: PluginEvent; team: Team; groupStoreForBatch: GroupStoreForBatch }

type PrefetchGroupEntry = { teamId: number; groupTypeIndex: GroupTypeIndex; groupKey: string; batchId: number }

/**
 * Warms the group cache for `$groupidentify` events in the chunk with one multi-key query per
 * batch store, so cold group keys don't each pay a sequential per-event SELECT inside the
 * per-distinct_id lane. Group type indexes are resolved read-only from the cached group-type
 * mappings — an unknown type means the group can't exist yet, so we skip it and let the normal
 * create path register the type. Fire-and-forget: the per-key fetch promises registered inside
 * `prefetchGroups` let the get-or-fetch path dedupe and surface errors.
 */
export function prefetchGroupsStep<T extends PrefetchGroupsStepInput>(
    enabled: boolean,
    groupTypeManager: GroupTypeManager
) {
    return async function prefetchGroupsStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled && events.length > 0) {
            const projectIds = new Set<ProjectId>()
            for (const event of events) {
                if (event.event.event === '$groupidentify') {
                    projectIds.add(event.team.project_id)
                }
            }

            if (projectIds.size > 0) {
                const groupTypesByProject = await groupTypeManager.fetchGroupTypesForProjects(projectIds)

                // Events in a chunk may come from different Kafka batches (due to the feed primitive).
                // Group by batch store so each store only receives entries it owns. Fire without
                // awaiting — the get-or-fetch path in getGroup will wait on the pending promises if
                // it needs data that's still being fetched.
                const entriesByStore = new Map<GroupStoreForBatch, PrefetchGroupEntry[]>()

                for (const event of events) {
                    if (event.event.event !== '$groupidentify') {
                        continue
                    }
                    const properties = event.event.properties
                    const groupType = properties?.['$group_type']
                    const groupKey = properties?.['$group_key']
                    if (!groupType || groupKey === undefined || groupKey === null) {
                        continue
                    }
                    const groupTypeIndex = groupTypesByProject[event.team.project_id]?.[groupType]
                    if (groupTypeIndex === undefined) {
                        continue
                    }

                    let entries = entriesByStore.get(event.groupStoreForBatch)
                    if (!entries) {
                        entries = []
                        entriesByStore.set(event.groupStoreForBatch, entries)
                    }
                    entries.push({
                        teamId: event.team.id,
                        groupTypeIndex,
                        groupKey: sanitizeString(groupKey.toString()),
                        batchId: event.groupStoreForBatch.batchId,
                    })
                }

                for (const [store, entries] of entriesByStore) {
                    void store.prefetchGroups(entries)
                }
            }
        }
        return events.map((event) => ok(event))
    }
}
