import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { GroupRepository } from '~/common/groups/repositories/group-repository.interface'
import { GroupsOutput, IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { TeamManager } from '~/common/utils/team-manager'
import { BatchWritingGroupStore } from '~/ingestion/common/groups/batch-writing-group-store'
import { BatchBoundGroupStore, GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { createProcessGroupsStep } from '~/ingestion/common/steps/event-processing/process-groups-step'
import { PipelineResultType } from '~/ingestion/framework/results'
import { prefetchGroupsStep } from '~/ingestion/pipelines/analytics/steps/prefetchGroupsStep'
import { PluginEvent } from '~/plugin-scaffold'
import { PreIngestionEvent, ProjectId, Team } from '~/types'

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
            // falsy $group_key is skipped, matching the upsert path's check
            createInput('$groupidentify', { $group_type: 'company', $group_key: '' }, 3, 10, store),
            // unresolved group type (not in the cached mapping) is skipped
            createInput('$groupidentify', { $group_type: 'unknown', $group_key: 'x' }, 3, 10, store),
        ])

        expect(results.map((result) => result.type)).toEqual([
            PipelineResultType.OK,
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

    // End-to-end key alignment: the prefetch must cache under the exact key the upsert path
    // looks up, or the warmed entries are never read and the upsert pays its per-key fetch anyway.
    it.each([
        ['a key with a null byte', 'acme\u0000corp', 'acme\uFFFDcorp'],
        ['a numeric key', 42, '42'],
    ])(
        'prefetched entries are read by a subsequent upsert for the same event with %s',
        async (_desc, rawKey, normalizedKey) => {
            let lastTx: { fetchGroup: jest.Mock; insertGroup: jest.Mock; updateGroup: jest.Mock } | null = null
            const groupRepository = {
                fetchGroups: jest.fn().mockResolvedValue([]),
                fetchGroup: jest.fn().mockResolvedValue(undefined),
                inTransaction: jest.fn().mockImplementation(async (_description, transaction) => {
                    lastTx = {
                        fetchGroup: jest.fn().mockResolvedValue(undefined),
                        insertGroup: jest.fn().mockResolvedValue(1),
                        updateGroup: jest.fn().mockResolvedValue(1),
                    }
                    return await transaction(lastTx)
                }),
            } as unknown as GroupRepository
            const clickhouseGroupRepository = {
                upsertGroup: jest.fn().mockResolvedValue(undefined),
            } as unknown as ClickhouseGroupRepository
            const outputs = {} as unknown as IngestionOutputs<GroupsOutput | IngestionWarningsOutput>
            const groupStore = new BatchWritingGroupStore(outputs, groupRepository, clickhouseGroupRepository, {
                metricEmissionIntervalMs: 0,
            })
            const boundStore = new BatchBoundGroupStore(groupStore, 0)

            const properties = { $group_type: 'company', $group_key: rawKey, $group_set: { a: '1' } }
            const groupTypeManager = {
                fetchGroupTypesForProjects: jest.fn().mockResolvedValue({ 10: { company: 0 } }),
                fetchGroupTypeIndex: jest.fn().mockResolvedValue(0),
            } as unknown as GroupTypeManager

            const step = prefetchGroupsStep<TestInput>(true, groupTypeManager)
            await step([createInput('$groupidentify', properties, 3, 10, boundStore)])
            // Let the fire-and-forget prefetch land in the cache (mocked repo resolves immediately).
            await new Promise((resolve) => setImmediate(resolve))
            expect(groupRepository.fetchGroups).toHaveBeenCalledTimes(1)

            const processStep = createProcessGroupsStep(
                { setTeamIngestedEvent: jest.fn() } as unknown as TeamManager,
                groupTypeManager,
                { SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: true }
            )
            await processStep({
                preparedEvent: {
                    eventUuid: 'test-uuid',
                    event: '$groupidentify',
                    teamId: 3,
                    projectId: 10 as ProjectId,
                    distinctId: 'd1',
                    properties,
                    timestamp: '2023-01-01T00:00:00.000Z',
                } as unknown as PreIngestionEvent,
                team: { id: 3, project_id: 10 as ProjectId } as unknown as Team,
                processPerson: true,
                groupStoreForBatch: boundStore,
            })

            // The upsert was served from the prefetched (negative) cache entry: no per-key fetch,
            // straight to the create path under the same normalized key the prefetch used.
            expect(groupRepository.fetchGroup).not.toHaveBeenCalled()
            expect(lastTx!.fetchGroup).not.toHaveBeenCalled()
            expect(lastTx!.insertGroup).toHaveBeenCalledWith(
                3,
                0,
                normalizedKey,
                { a: '1' },
                expect.anything(),
                expect.anything(),
                expect.anything()
            )

            await groupStore.shutdown()
        }
    )
})
