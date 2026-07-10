import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { prefetchGroupsStep } from '~/ingestion/pipelines/analytics/steps/prefetchGroupsStep'
import { PipelineEvent, Team } from '~/types'

type TestInput = { event: PipelineEvent; team: Team; groupStoreForBatch: GroupStoreForBatch }

function createStore(batchId: number): GroupStoreForBatch {
    return {
        batchId,
        prefetchGroups: jest.fn().mockResolvedValue(undefined),
    } as unknown as GroupStoreForBatch
}

function createInput(
    eventName: string,
    properties: Record<string, any>,
    teamId: number,
    groupStoreForBatch: GroupStoreForBatch
): TestInput {
    return {
        event: { event: eventName, properties } as unknown as PipelineEvent,
        team: { id: teamId, project_id: teamId } as unknown as Team,
        groupStoreForBatch,
    }
}

describe('prefetchGroupsStep', () => {
    let groupTypeManager: GroupTypeManager

    beforeEach(() => {
        groupTypeManager = {
            fetchGroupTypes: jest.fn().mockResolvedValue({ organization: 0, project: 1 }),
        } as unknown as GroupTypeManager
    })

    it('prefetches only $groupidentify events with known group types', async () => {
        const store = createStore(1)
        const step = prefetchGroupsStep<TestInput>(groupTypeManager, true)

        const results = await step([
            createInput('$groupidentify', { $group_type: 'organization', $group_key: 'org-1' }, 3, store),
            createInput('$pageview', { $group_type: 'organization', $group_key: 'org-2' }, 3, store),
            // Unknown group type — would require an insert, so it's skipped.
            createInput('$groupidentify', { $group_type: 'brand-new-type', $group_key: 'x' }, 3, store),
            createInput('$groupidentify', { $group_type: 'project', $group_key: 42 }, 4, store),
            createInput('$groupidentify', { $group_type: 'organization' }, 3, store),
        ])

        expect(results.every((result) => result.type === PipelineResultType.OK)).toBe(true)
        expect(results.filter(isOkResult)).toHaveLength(5)
        expect(store.prefetchGroups).toHaveBeenCalledWith([
            { teamId: 3, groupTypeIndex: 0, groupKey: 'org-1', batchId: 1 },
            { teamId: 4, groupTypeIndex: 1, groupKey: '42', batchId: 1 },
        ])
    })

    it('passes events through without prefetching when disabled', async () => {
        const store = createStore(1)
        const step = prefetchGroupsStep<TestInput>(groupTypeManager, false)

        const results = await step([
            createInput('$groupidentify', { $group_type: 'organization', $group_key: 'org-1' }, 3, store),
        ])

        expect(results.map((result) => result.type)).toEqual([PipelineResultType.OK])
        expect(store.prefetchGroups).not.toHaveBeenCalled()
    })
})
