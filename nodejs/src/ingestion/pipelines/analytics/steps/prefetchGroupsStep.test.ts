import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { PipelineResultType } from '~/ingestion/framework/results'
import { prefetchGroupsStep } from '~/ingestion/pipelines/analytics/steps/prefetchGroupsStep'
import { PluginEvent } from '~/plugin-scaffold'
import { ProjectId, Team } from '~/types'

type TestInput = { event: PluginEvent; team: Team; groupStoreForBatch: GroupStoreForBatch }

function createStore(batchId: number): GroupStoreForBatch {
    return {
        batchId,
        prefetchGroups: jest.fn().mockResolvedValue(undefined),
    } as unknown as GroupStoreForBatch
}

function createGroupTypeManager(mapping: Record<number, Record<string, number>>): GroupTypeManager {
    return {
        fetchGroupTypesForProjects: jest.fn().mockResolvedValue(mapping),
    } as unknown as GroupTypeManager
}

function createInput(
    eventName: string,
    properties: Record<string, unknown>,
    teamId: number,
    projectId: number,
    groupStoreForBatch: GroupStoreForBatch
): TestInput {
    return {
        event: { event: eventName, properties } as unknown as PluginEvent,
        team: { id: teamId, project_id: projectId as ProjectId } as unknown as Team,
        groupStoreForBatch,
    }
}

describe('prefetchGroupsStep', () => {
    it('collects resolvable $groupidentify keys and skips other events, missing keys, and unknown types', async () => {
        const store = createStore(1)
        const groupTypeManager = createGroupTypeManager({ 10: { company: 0 } })
        const step = prefetchGroupsStep<TestInput>(true, groupTypeManager)

        const results = await step([
            createInput('$groupidentify', { $group_type: 'company', $group_key: 'acme' }, 3, 10, store),
            // non-$groupidentify event is ignored
            createInput('$pageview', { $group_type: 'company', $group_key: 'other' }, 3, 10, store),
            // missing $group_key is skipped
            createInput('$groupidentify', { $group_type: 'company' }, 3, 10, store),
            // unresolved group type (not in the cached mapping) is skipped
            createInput('$groupidentify', { $group_type: 'unknown', $group_key: 'x' }, 3, 10, store),
        ])

        expect(results.map((result) => result.type)).toEqual([
            PipelineResultType.OK,
            PipelineResultType.OK,
            PipelineResultType.OK,
            PipelineResultType.OK,
        ])
        expect(store.prefetchGroups).toHaveBeenCalledWith([
            { teamId: 3, groupTypeIndex: 0, groupKey: 'acme', batchId: 1 },
        ])
    })

    it('groups entries by batch store', async () => {
        const storeA = createStore(1)
        const storeB = createStore(2)
        const groupTypeManager = createGroupTypeManager({ 10: { company: 0 } })
        const step = prefetchGroupsStep<TestInput>(true, groupTypeManager)

        await step([
            createInput('$groupidentify', { $group_type: 'company', $group_key: 'a' }, 3, 10, storeA),
            createInput('$groupidentify', { $group_type: 'company', $group_key: 'b' }, 4, 10, storeB),
            createInput('$groupidentify', { $group_type: 'company', $group_key: 'c' }, 5, 10, storeA),
        ])

        expect(storeA.prefetchGroups).toHaveBeenCalledWith([
            { teamId: 3, groupTypeIndex: 0, groupKey: 'a', batchId: 1 },
            { teamId: 5, groupTypeIndex: 0, groupKey: 'c', batchId: 1 },
        ])
        expect(storeB.prefetchGroups).toHaveBeenCalledWith([
            { teamId: 4, groupTypeIndex: 0, groupKey: 'b', batchId: 2 },
        ])
    })

    it('passes events through without prefetching when disabled', async () => {
        const store = createStore(1)
        const groupTypeManager = createGroupTypeManager({ 10: { company: 0 } })
        const step = prefetchGroupsStep<TestInput>(false, groupTypeManager)

        const results = await step([
            createInput('$groupidentify', { $group_type: 'company', $group_key: 'acme' }, 3, 10, store),
        ])

        expect(results.map((result) => result.type)).toEqual([PipelineResultType.OK])
        expect(store.prefetchGroups).not.toHaveBeenCalled()
        expect(groupTypeManager.fetchGroupTypesForProjects).not.toHaveBeenCalled()
    })
})
