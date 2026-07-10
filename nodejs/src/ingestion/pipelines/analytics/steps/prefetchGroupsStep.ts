import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { sanitizeString } from '~/common/utils/db/utils'
import { GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { GroupTypeIndex, PipelineEvent, Team, TeamId } from '~/types'

type PrefetchGroupsStepInput = { event: PipelineEvent; team: Team; groupStoreForBatch: GroupStoreForBatch }

type PrefetchGroupEntry = { teamId: TeamId; groupTypeIndex: GroupTypeIndex; groupKey: string; batchId: number }

/**
 * Warms the group cache for all $groupidentify events in the chunk with one
 * batched query per store, instead of a single-row fetch per group key during
 * event processing. Group type indexes are resolved through the
 * GroupTypeManager's cached mapping only — unknown group types (which would
 * require an insert) are skipped and handled by processGroupsStep.
 */
export function prefetchGroupsStep<T extends PrefetchGroupsStepInput>(
    groupTypeManager: GroupTypeManager,
    enabled: boolean
) {
    return async function prefetchGroupsStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled && events.length > 0) {
            // Events in a chunk may come from different Kafka batches (due to the feed primitive).
            // Group by batch store so each store only receives entries it owns. Fire without
            // awaiting — getGroup will wait on the pending promises if it needs data that's
            // still being fetched.
            const entriesByStore = new Map<GroupStoreForBatch, PrefetchGroupEntry[]>()

            for (const event of events) {
                if (event.event.event !== '$groupidentify') {
                    continue
                }
                const properties = event.event.properties ?? {}
                const groupType = properties['$group_type']
                const groupKey = properties['$group_key']
                if (!groupType || !groupKey) {
                    continue
                }

                const groupTypes = await groupTypeManager.fetchGroupTypes(event.team.project_id)
                const groupTypeIndex = groupTypes[groupType]
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
                    groupKey: sanitizeString(String(groupKey)),
                    batchId: event.groupStoreForBatch.batchId,
                })
            }

            for (const [store, entries] of entriesByStore) {
                void store.prefetchGroups(entries)
            }
        }
        return events.map((event) => ok(event))
    }
}
