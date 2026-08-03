// sort-imports-ignore
import { DateTime } from 'luxon'

import { Group, GroupTypeIndex, ProjectId, TeamId } from '~/types'
import { parseJSON } from '~/common/utils/json-parse'
import { RaceConditionError } from '~/common/utils/utils'

import { BatchWritingGroupStore } from './batch-writing-group-store'
import { groupCacheOperationsCounter } from './metrics'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { GroupCreateResult, GroupRepository } from '~/common/groups/repositories/group-repository.interface'

import { GroupsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'

// Mock the DB class

describe('BatchWritingGroupStore', () => {
    let groupRepository: GroupRepository
    let groupStore: BatchWritingGroupStore
    let clickhouseGroupRepository: ClickhouseGroupRepository
    let mockQueueMessages: jest.Mock
    let teamId: TeamId
    let projectId: ProjectId
    let group: Group

    beforeEach(() => {
        teamId = 1
        projectId = 1 as ProjectId
        // Create a mock DB instance with all required methods
        group = {
            id: 1,
            team_id: teamId,
            group_type_index: 1,
            group_key: 'test',
            group_properties: { test: 'test' },
            created_at: DateTime.now(),
            version: 1,
            properties_last_updated_at: {},
            properties_last_operation: {},
        }

        let dbCounter = 0

        // Create a mock GroupRepository
        groupRepository = {
            fetchGroup: jest.fn().mockImplementation(() => {
                return Promise.resolve(group)
            }),
            fetchGroupsByKeys: jest.fn().mockResolvedValue([]),
            updateGroupsBatch: jest.fn().mockResolvedValue([]),
            insertGroupsBatch: jest.fn().mockResolvedValue([]),
            insertGroup: jest.fn().mockImplementation(() => {
                return Promise.resolve(1)
            }),
            updateGroup: jest.fn().mockImplementation(() => {
                dbCounter++
                return Promise.resolve(dbCounter)
            }),
            updateGroupOptimistically: jest.fn().mockImplementation(() => {
                dbCounter++
                return Promise.resolve(dbCounter)
            }),
            inTransaction: jest.fn().mockImplementation(async (_description, transaction) => {
                // Create a proper mock transaction with the required methods
                const mockTransaction = {
                    fetchGroup: jest.fn().mockImplementation(() => {
                        return Promise.resolve(group)
                    }),
                    insertGroup: jest.fn().mockImplementation(() => {
                        return Promise.resolve(1)
                    }),
                    updateGroup: jest.fn().mockImplementation(() => {
                        dbCounter++
                        return Promise.resolve(dbCounter)
                    }),
                }
                return await transaction(mockTransaction)
            }),
        } as unknown as GroupRepository

        // Store the transaction mock for assertions
        ;(groupRepository as any).lastTransactionMock = null
        groupRepository.inTransaction = jest.fn().mockImplementation(async (_description, transaction) => {
            const mockTransaction = {
                fetchGroup: jest.fn().mockImplementation(() => {
                    return Promise.resolve(group)
                }),
                insertGroup: jest.fn().mockImplementation(() => {
                    return Promise.resolve(1)
                }),
                updateGroup: jest.fn().mockImplementation(() => {
                    dbCounter++
                    return Promise.resolve(dbCounter)
                }),
            }
            ;(groupRepository as any).lastTransactionMock = mockTransaction
            return await transaction(mockTransaction)
        })

        // Reset the counter before each test
        groupCacheOperationsCounter.reset()

        // Real repository over a mocked producer: buildUpsertMessage is pure,
        // and only the inline create/fallback paths call queueMessages.
        mockQueueMessages = jest.fn().mockResolvedValue(undefined)
        clickhouseGroupRepository = new ClickhouseGroupRepository({
            queueMessages: mockQueueMessages,
        } as unknown as IngestionOutputs<GroupsOutput>)
        // Pin the individual CAS flush path: it remains the fallback for
        // missing rows and failed batch statements, so this block keeps it
        // covered while `useBatchUpdates` describes the default batched path.
        groupStore = new BatchWritingGroupStore(groupRepository, clickhouseGroupRepository, {
            useBatchUpdates: false,
        })
    })

    afterEach(async () => {
        // Clear the metric-emission interval started in the constructor;
        // unref() prevents it from blocking process exit, but we still want
        // a clean slate between tests. Tests may leave dirty entries behind,
        // so flush first — shutdown() throws on dirty cache by design.
        try {
            await groupStore?.flush()
        } catch {
            // ignore — some tests intentionally fail flush
        }
        try {
            await groupStore?.shutdown()
        } catch {
            // ignore — some tests intentionally leave the cache dirty
        }
        jest.clearAllMocks()
    })

    it('should accumulate writes in cache, write once to db', async () => {
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, DateTime.now())
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { c: 'test' }, DateTime.now())

        const results = await groupStore.flush()

        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.insertGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0) // Uses optimistic update for existing groups
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
            teamId,
            1,
            'test',
            1,
            { a: 'test', b: 'test', c: 'test', test: 'test' },
            group.created_at,
            {},
            {}
        )

        // The ClickHouse message is returned for side-effect production, not produced inline.
        expect(results).toHaveLength(1)
        expect(results[0]).toMatchObject({ teamId, groupTypeIndex: 1, groupKey: 'test' })
        expect(results[0].messages).toHaveLength(1)
        expect(mockQueueMessages).not.toHaveBeenCalled()

        const cacheMetrics = groupStore.getCacheMetrics()

        expect(cacheMetrics.cacheHits).toBe(2)
        expect(cacheMetrics.cacheMisses).toBe(0)
    })

    it('should immediately write to db if new group', async () => {
        jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(undefined)
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())

        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(0)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        // Creation is a single ON CONFLICT insert — no wrapping transaction.
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0)
        expect(groupRepository.insertGroup).toHaveBeenCalledTimes(1)
        // The ClickHouse message is NOT awaited inline (delivery reports on a
        // backpressured producer stall the sequential per-distinct-id lane);
        // it rides the next flush's side effects instead.
        expect(mockQueueMessages).not.toHaveBeenCalled()

        const results = await groupStore.flush()
        expect(results).toHaveLength(1)
        expect(results[0]).toMatchObject({ teamId, groupTypeIndex: 1, groupKey: 'test' })
    })

    it('should accumulate changes in cache after db write, even if new group', async () => {
        jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(undefined)
        const createdAt = DateTime.now()

        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, createdAt)
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, createdAt)

        await groupStore.flush()

        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0)
        expect(groupRepository.insertGroup).toHaveBeenCalledTimes(1)

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
            teamId,
            1,
            'test',
            1,
            { a: 'test', b: 'test' },
            createdAt,
            {},
            {}
        )
    })

    it('should retry optimistic update if version mismatch', async () => {
        let fetchCounter = 0
        let updateCounter = 0
        jest.spyOn(groupRepository, 'fetchGroup').mockImplementation(() => {
            fetchCounter++
            if (fetchCounter === 1) {
                return Promise.resolve(group)
            } else {
                const updatedGroup = {
                    ...group,
                    version: fetchCounter,
                }
                return Promise.resolve(updatedGroup)
            }
        })
        jest.spyOn(groupRepository, 'updateGroupOptimistically').mockImplementation(() => {
            updateCounter++
            if (updateCounter < 3) {
                // Fail the first two updates
                return Promise.resolve(undefined)
            }
            return Promise.resolve(updateCounter)
        })

        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, DateTime.now())
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { c: 'test' }, DateTime.now())

        await groupStore.flush()

        // Should fetch 3 times, 1 for initial fetch, 2 for retries
        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(3)
        // Should make 3 updates, 2 failed, 1 successful
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(3)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0) // Uses optimistic updates, not transactions

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
            teamId,
            1,
            'test',
            3,
            { a: 'test', b: 'test', c: 'test', test: 'test' },
            group.created_at,
            {},
            {}
        )
    })

    it('should fall back to direct upsert if optimistic update fails', async () => {
        jest.spyOn(groupRepository, 'updateGroupOptimistically').mockResolvedValue(undefined)
        jest.spyOn(groupRepository, 'updateGroup').mockResolvedValue(2)
        // Conflict refetches return a group WITHOUT our properties, so the
        // short-circuit doesn't kick in and every attempt retries.
        jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(group)
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'updated' }, DateTime.now())

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(0)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(mockQueueMessages).toHaveBeenCalledTimes(0)

        const results = await groupStore.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(5)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(1)
        expect((groupRepository as any).lastTransactionMock.updateGroup).toHaveBeenCalledTimes(1)
        // The fallback path's ClickHouse message rides this flush's results
        // instead of being produced inline.
        expect(mockQueueMessages).not.toHaveBeenCalled()
        expect(results).toHaveLength(1)
    })

    it('should share cache between distinct ids', async () => {
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { b: 'test' }, DateTime.now())

        await groupStore.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0) // Uses optimistic update for existing groups
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
            teamId,
            1,
            'test',
            1,
            { a: 'test', b: 'test', test: 'test' },
            group.created_at,
            {},
            {}
        )
    })

    it('keeps separate cache entries for two group types sharing a group key', async () => {
        // A cache key without group_type_index would make the second upsert
        // read the first type's cached row, merge both types' properties into
        // one entry, and flush a single contaminated write.
        jest.spyOn(groupRepository, 'fetchGroup').mockImplementation((_teamId, groupTypeIndex) =>
            Promise.resolve({ ...group, group_type_index: groupTypeIndex, group_properties: {} })
        )

        await groupStore.upsertGroup(teamId, projectId, 0, 'shared-key', { a: '1' }, DateTime.now())
        await groupStore.upsertGroup(teamId, projectId, 1, 'shared-key', { b: '2' }, DateTime.now())

        await groupStore.flush()

        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(2)
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(2)
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
            teamId,
            0,
            'shared-key',
            1,
            { a: '1' },
            group.created_at,
            {},
            {}
        )
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
            teamId,
            1,
            'shared-key',
            1,
            { b: '2' },
            group.created_at,
            {},
            {}
        )
    })

    it('should not write to db if no properties are changed', async () => {
        // Mock the groupRepository.fetchGroup to return a group with the same properties
        jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(group)

        await groupStore.upsertGroup(teamId, projectId, 1, 'test', group.group_properties, DateTime.now())

        await groupStore.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(0)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0)
        // No transaction calls expected since no properties changed
    })

    it('should retry on race condition error and clear cache', async () => {
        let fetchCounter = 0
        jest.spyOn(groupRepository, 'fetchGroup').mockImplementation(() => {
            fetchCounter++
            if (fetchCounter === 1) {
                return Promise.resolve(undefined)
            } else {
                return Promise.resolve(group)
            }
        })

        // The group was created by another pod between our fetch and insert.
        jest.spyOn(groupRepository, 'insertGroup').mockRejectedValueOnce(
            new RaceConditionError('Parallel posthog_group inserts, retry')
        )

        // track cache delete
        const groupCache = groupStore.getGroupCache()
        const cacheDeleteSpy = jest.spyOn(groupCache, 'delete')

        // Add to cache to verify it gets cleared on race condition
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())

        await groupStore.flush()

        expect(groupRepository.insertGroup).toHaveBeenCalledTimes(1)
        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(2) // Once for initial fetch, once for retry
        expect(cacheDeleteSpy).toHaveBeenCalledWith(teamId, 1, 'test')

        // The retry found the winning row and flushed our properties onto it.
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroupOptimistically).toHaveBeenLastCalledWith(
            teamId,
            1,
            'test',
            1, // version from second fetch
            { a: 'test', test: 'test' },
            group.created_at,
            {},
            {}
        )
    })

    it('should not write when object-valued properties are deeply equal', async () => {
        // Object values arrive as fresh JSON parses each event; a reference
        // compare here would dirty the group on every event and re-open the
        // no-op write storm this store had in production.
        group.group_properties = { nested: { plan: 'scale', seats: 5 } }

        await groupStore.upsertGroup(
            teamId,
            projectId,
            1,
            'test',
            { nested: { plan: 'scale', seats: 5 } },
            DateTime.now()
        )
        const results = await groupStore.flush()

        expect(results).toHaveLength(0)
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(0)
    })

    it('should skip the retry when a conflicting writer already persisted the same properties', async () => {
        jest.spyOn(groupRepository, 'updateGroupOptimistically').mockResolvedValue(undefined)
        jest.spyOn(groupRepository, 'fetchGroup')
            .mockResolvedValueOnce(group)
            .mockResolvedValue({ ...group, group_properties: { test: 'test', a: 'test' }, version: 7 })

        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())
        const results = await groupStore.flush()

        // One failed CAS, then the refetch shows the winner already wrote our
        // properties — no retries, no fallback, no ClickHouse message.
        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0)
        expect(results).toHaveLength(0)
        expect(groupStore.getGroupCache().get(teamId, 1, 'test')?.version).toBe(7)
    })

    describe('useBatchUpdates', () => {
        beforeEach(() => {
            groupStore = new BatchWritingGroupStore(groupRepository, clickhouseGroupRepository, {
                useBatchUpdates: true,
            })
        })

        it('flushes all dirty groups in one statement, routing each merged row and fallback to its own group', async () => {
            // Each group gets its own row back, distinct rows include keys the
            // DB merged from other pods, and one group is missing from the
            // result (deleted or never created) so it falls back to an
            // individual write.
            jest.spyOn(groupRepository, 'fetchGroup').mockImplementation((_teamId, groupTypeIndex, groupKey) =>
                Promise.resolve({ ...group, group_type_index: groupTypeIndex, group_key: groupKey })
            )
            const rowA = {
                ...group,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'g-a',
                group_properties: { test: 'test', a: '1', from_other_pod: 'x' },
                version: 5,
            }
            const rowB = {
                ...group,
                group_type_index: 1 as GroupTypeIndex,
                group_key: 'g-b',
                group_properties: { test: 'test', b: '2' },
                version: 9,
            }
            jest.spyOn(groupRepository, 'updateGroupsBatch').mockResolvedValue([rowA, rowB])

            await groupStore.upsertGroup(teamId, projectId, 0, 'g-a', { a: '1' }, DateTime.now())
            await groupStore.upsertGroup(teamId, projectId, 1, 'g-b', { b: '2' }, DateTime.now())
            await groupStore.upsertGroup(teamId, projectId, 0, 'g-missing', { c: '3' }, DateTime.now())

            const results = await groupStore.flush()

            expect(groupRepository.updateGroupsBatch).toHaveBeenCalledTimes(1)
            expect(groupRepository.updateGroupsBatch).toHaveBeenCalledWith([
                {
                    teamId,
                    groupTypeIndex: 0,
                    groupKey: 'g-a',
                    propertiesToSet: { a: '1' },
                    createdAt: group.created_at,
                },
                {
                    teamId,
                    groupTypeIndex: 1,
                    groupKey: 'g-b',
                    propertiesToSet: { b: '2' },
                    createdAt: group.created_at,
                },
                {
                    teamId,
                    groupTypeIndex: 0,
                    groupKey: 'g-missing',
                    propertiesToSet: { c: '3' },
                    createdAt: group.created_at,
                },
            ])

            // Only the group missing from the batch result goes through the individual path.
            expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
            expect(jest.mocked(groupRepository.updateGroupOptimistically).mock.calls[0][2]).toBe('g-missing')

            // Each ClickHouse message reflects that group's own authoritative row.
            expect(results).toHaveLength(3)
            const messagesByKey = new Map(
                results.map((result) => [result.groupKey, parseJSON(result.messages[0].value.toString())])
            )
            expect(parseJSON(messagesByKey.get('g-a').group_properties)).toEqual(rowA.group_properties)
            expect(messagesByKey.get('g-a').version).toBe(5)
            expect(messagesByKey.get('g-a').group_type_index).toBe(0)
            expect(parseJSON(messagesByKey.get('g-b').group_properties)).toEqual(rowB.group_properties)
            expect(messagesByKey.get('g-b').version).toBe(9)
            expect(messagesByKey.get('g-b').group_type_index).toBe(1)

            // The cache converges on each group's own merged row.
            expect(groupStore.getGroupCache().get(teamId, 0, 'g-a')?.version).toBe(5)
            expect(groupStore.getGroupCache().get(teamId, 0, 'g-a')?.group_properties).toEqual(rowA.group_properties)
            expect(groupStore.getGroupCache().get(teamId, 1, 'g-b')?.version).toBe(9)
            expect(groupStore.getGroupCache().get(teamId, 1, 'g-b')?.group_properties).toEqual(rowB.group_properties)
        })

        it('falls back to individual writes when the batch statement fails', async () => {
            jest.spyOn(groupRepository, 'updateGroupsBatch').mockRejectedValue(new Error('connection lost'))

            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now())
            const results = await groupStore.flush()

            expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
            expect(results).toHaveLength(1)
        })
    })

    describe('useBatchCreates', () => {
        beforeEach(() => {
            // Updates pinned to the individual path so create-routing
            // assertions stay independent of the update flush mode.
            groupStore = new BatchWritingGroupStore(groupRepository, clickhouseGroupRepository, {
                useBatchCreates: true,
                useBatchUpdates: false,
            })
        })

        it('defers new groups to flush and inserts them in one statement, leaving updates on their own path', async () => {
            const timestamp = DateTime.now()
            // 'test' exists; the two new keys don't.
            jest.spyOn(groupRepository, 'fetchGroup').mockImplementation((_teamId, _groupTypeIndex, groupKey) =>
                Promise.resolve(groupKey === 'test' ? group : undefined)
            )
            const rowA = {
                ...group,
                group_type_index: 0 as GroupTypeIndex,
                group_key: 'new-a',
                group_properties: { a: '1' },
                created_at: timestamp,
                version: 1,
                inserted: true,
            }
            const rowB = {
                ...group,
                group_type_index: 1 as GroupTypeIndex,
                group_key: 'new-b',
                group_properties: { b: '2' },
                created_at: timestamp,
                version: 1,
                inserted: true,
            }
            jest.spyOn(groupRepository, 'insertGroupsBatch').mockResolvedValue([rowA, rowB])

            await groupStore.upsertGroup(teamId, projectId, 0, 'new-a', { a: '1' }, timestamp)
            await groupStore.upsertGroup(teamId, projectId, 1, 'new-b', { b: '2' }, timestamp)
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { u: '1' }, timestamp)

            // No inline insert during event processing.
            expect(groupRepository.insertGroup).not.toHaveBeenCalled()
            expect(groupRepository.insertGroupsBatch).not.toHaveBeenCalled()

            const results = await groupStore.flush()

            expect(groupRepository.insertGroup).not.toHaveBeenCalled()
            expect(groupRepository.insertGroupsBatch).toHaveBeenCalledTimes(1)
            expect(groupRepository.insertGroupsBatch).toHaveBeenCalledWith([
                { teamId, groupTypeIndex: 0, groupKey: 'new-a', groupProperties: { a: '1' }, createdAt: timestamp },
                { teamId, groupTypeIndex: 1, groupKey: 'new-b', groupProperties: { b: '2' }, createdAt: timestamp },
            ])
            // The existing group still goes through the regular update path.
            expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
            expect(jest.mocked(groupRepository.updateGroupOptimistically).mock.calls[0][2]).toBe('test')

            // Each created group's ClickHouse message reflects its returned row.
            expect(results).toHaveLength(3)
            const messagesByKey = new Map(
                results.map((result) => [result.groupKey, parseJSON(result.messages[0].value.toString())])
            )
            expect(parseJSON(messagesByKey.get('new-a').group_properties)).toEqual({ a: '1' })
            expect(messagesByKey.get('new-a').version).toBe(1)
            expect(parseJSON(messagesByKey.get('new-b').group_properties)).toEqual({ b: '2' })
            expect(messagesByKey.get('new-b').version).toBe(1)

            // The cache converges on the authoritative inserted rows.
            expect(groupStore.getGroupCache().get(teamId, 0, 'new-a')?.version).toBe(1)
            expect(groupStore.getGroupCache().get(teamId, 1, 'new-b')?.version).toBe(1)
        })

        it('accumulates repeated events for a new group into a single creation', async () => {
            const timestamp = DateTime.now()
            jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(undefined)
            jest.spyOn(groupRepository, 'insertGroupsBatch').mockResolvedValue([
                { ...group, group_key: 'new-key', group_properties: { a: '2', b: 'x' }, version: 1, inserted: true },
            ])

            await groupStore.upsertGroup(teamId, projectId, 1, 'new-key', { a: '1' }, timestamp)
            await groupStore.upsertGroup(teamId, projectId, 1, 'new-key', { a: '2', b: 'x' }, timestamp)

            await groupStore.flush()

            // One fetch, one batched insert carrying the merged view (later event wins).
            expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(1)
            expect(groupRepository.insertGroupsBatch).toHaveBeenCalledTimes(1)
            expect(groupRepository.insertGroupsBatch).toHaveBeenCalledWith([
                {
                    teamId,
                    groupTypeIndex: 1,
                    groupKey: 'new-key',
                    groupProperties: { a: '2', b: 'x' },
                    createdAt: timestamp,
                },
            ])
        })

        it('takes the merged row when a creation lost the cross-pod race, without extra round trips', async () => {
            const timestamp = DateTime.now()
            jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValueOnce(undefined)
            // The row already existed: the statement merged our properties onto
            // the winner's row and flags it as not-inserted.
            jest.spyOn(groupRepository, 'insertGroupsBatch').mockResolvedValue([
                {
                    ...group,
                    group_key: 'new-key',
                    group_properties: { test: 'test', a: '1' },
                    version: 6,
                    inserted: false,
                },
            ])

            await groupStore.upsertGroup(teamId, projectId, 1, 'new-key', { a: '1' }, timestamp)
            const results = await groupStore.flush()

            // No refetch, no CAS, no per-row insert — the merge already happened.
            expect(groupRepository.insertGroup).not.toHaveBeenCalled()
            expect(groupRepository.updateGroupOptimistically).not.toHaveBeenCalled()
            expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(1)
            expect(results).toHaveLength(1)
            const message = parseJSON(results[0].messages[0].value.toString())
            expect(parseJSON(message.group_properties)).toEqual({ test: 'test', a: '1' })
            expect(message.version).toBe(6)
            expect(groupStore.getGroupCache().get(teamId, 1, 'new-key')?.version).toBe(6)
        })

        it('routes rows missing from the batch result through the individual update path', async () => {
            // Postgres returns one row per input, but a misbehaving repository
            // implementation (or a dropped guard) must not silently lose
            // creations — the residue converges through the standard CAS path.
            const timestamp = DateTime.now()
            jest.spyOn(groupRepository, 'fetchGroup')
                .mockResolvedValueOnce(undefined)
                .mockResolvedValue({ ...group, group_key: 'new-key', version: 5 })
            jest.spyOn(groupRepository, 'insertGroupsBatch').mockResolvedValue([])
            jest.spyOn(groupRepository, 'updateGroupOptimistically')
                .mockResolvedValueOnce(undefined) // version-0 CAS fails
                .mockResolvedValueOnce(6)

            await groupStore.upsertGroup(teamId, projectId, 1, 'new-key', { a: '1' }, timestamp)
            const results = await groupStore.flush()

            expect(groupRepository.insertGroup).not.toHaveBeenCalled()
            // Rebased onto the winner: version 5, our delta merged on top.
            expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(2)
            expect(groupRepository.updateGroupOptimistically).toHaveBeenLastCalledWith(
                teamId,
                1,
                'new-key',
                5,
                { test: 'test', a: '1' },
                timestamp,
                {},
                {}
            )
            expect(results).toHaveLength(1)
            expect(parseJSON(results[0].messages[0].value.toString()).version).toBe(6)
        })

        it('falls back to individual inserts when the batch create statement fails', async () => {
            const timestamp = DateTime.now()
            jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(undefined)
            jest.spyOn(groupRepository, 'insertGroupsBatch').mockRejectedValue(new Error('connection lost'))

            await groupStore.upsertGroup(teamId, projectId, 0, 'new-a', { a: '1' }, timestamp)
            await groupStore.upsertGroup(teamId, projectId, 1, 'new-b', { b: '2' }, timestamp)

            const results = await groupStore.flush()

            expect(groupRepository.insertGroup).toHaveBeenCalledTimes(2)
            expect(results).toHaveLength(2)
            const messagesByKey = new Map(
                results.map((result) => [result.groupKey, parseJSON(result.messages[0].value.toString())])
            )
            expect(parseJSON(messagesByKey.get('new-a').group_properties)).toEqual({ a: '1' })
            expect(parseJSON(messagesByKey.get('new-b').group_properties)).toEqual({ b: '2' })
        })

        it('claims pending creates synchronously at flush so a concurrent flush cannot double-insert', async () => {
            const timestamp = DateTime.now()
            jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(undefined)
            let resolveInsert: (rows: GroupCreateResult[]) => void = () => {}
            jest.spyOn(groupRepository, 'insertGroupsBatch').mockImplementation(
                () => new Promise<GroupCreateResult[]>((resolve) => (resolveInsert = resolve))
            )
            jest.spyOn(groupRepository, 'updateGroupOptimistically').mockResolvedValue(2)

            await groupStore.upsertGroup(teamId, projectId, 1, 'new-key', { a: '1' }, timestamp)

            // Kick off flush WITHOUT awaiting: the claim must happen before any
            // DB I/O, so pendingCreate is already cleared here.
            const firstFlush = groupStore.flush()
            const entry = groupStore.getGroupCache().get(teamId, 1, 'new-key')
            expect(entry?.pendingCreate).toBe(false)
            expect(entry?.needsWrite).toBe(false)

            // Re-dirty the key while the insert is still in flight — a second
            // flush must capture it as a regular update, not a second insert.
            await groupStore.upsertGroup(teamId, projectId, 1, 'new-key', { b: '2' }, timestamp)
            const secondFlush = groupStore.flush()

            resolveInsert([
                { ...group, group_key: 'new-key', group_properties: { a: '1' }, version: 1, inserted: true },
            ])
            await Promise.all([firstFlush, secondFlush])

            expect(groupRepository.insertGroupsBatch).toHaveBeenCalledTimes(1)
            expect(groupRepository.insertGroup).not.toHaveBeenCalled()
            expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
            // The insert's older row (version 1) must not regress the cache
            // entry the second flush already synced to its newer write.
            expect(groupStore.getGroupCache().get(teamId, 1, 'new-key')?.version).toBe(2)
        })
    })

    describe('prefetchGroups', () => {
        it('serves subsequent upserts from the prefetched cache without single-row fetches', async () => {
            jest.spyOn(groupRepository, 'fetchGroupsByKeys').mockResolvedValue([
                {
                    team_id: teamId,
                    group_type_index: 1,
                    group_key: 'test',
                    group_properties: { test: 'test' },
                    created_at: group.created_at,
                    version: 1,
                },
            ])

            await groupStore.prefetchGroups([
                { teamId, groupTypeIndex: 1, groupKey: 'test', batchId: 0 },
                { teamId, groupTypeIndex: 1, groupKey: 'missing', batchId: 0 },
            ])

            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now(), 0)
            // The missing key was negative-cached, so the create path goes
            // straight to insert without another read.
            await groupStore.upsertGroup(teamId, projectId, 1, 'missing', { b: '2' }, DateTime.now(), 0)

            expect(groupRepository.fetchGroupsByKeys).toHaveBeenCalledTimes(1)
            expect(groupRepository.fetchGroup).not.toHaveBeenCalled()
            expect(groupRepository.insertGroup).toHaveBeenCalledTimes(1)
        })
    })

    describe('persistent cache (concurrentBatches > 1)', () => {
        it('clears needsWrite on dirty entries synchronously during flush', async () => {
            // Linearization point: flush() must clear needsWrite BEFORE awaiting
            // any DB I/O. Any code path that introduces an await between the
            // dirty-filter pass and the clear would re-open the cross-batch
            // race documented in the design doc — this test guards against it.
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())

            const groupCache = groupStore.getGroupCache()
            const dirtyBefore = Array.from(groupCache.entries()).filter(([_, u]) => u && u.needsWrite)
            expect(dirtyBefore.length).toBeGreaterThan(0)

            // Kick off flush WITHOUT awaiting it, then synchronously inspect
            // needsWrite. If flush yields before clearing the flag, this will
            // catch it — the assertion runs at the first microtask boundary.
            const flushPromise = groupStore.flush()

            const stillDirty = Array.from(groupCache.entries()).filter(([_, u]) => u && u.needsWrite)
            expect(stillDirty).toHaveLength(0)

            await flushPromise
        })

        it('re-dirty during flush window drives the next flush', async () => {
            // After an entry is written and cleaned by a flush, a subsequent
            // upsert with new properties re-dirties it, and the next flush picks
            // up the delta.
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now())
            await groupStore.flush()
            ;(groupRepository.updateGroupOptimistically as jest.Mock).mockClear()

            // Re-dirty via a second update with new properties. The cache is
            // still referenced by batch 0 until releaseBatch() runs, so the
            // second update merges with the first batch's cached properties.
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { b: '2' }, DateTime.now())
            const dirtyAfter = Array.from(groupStore.getGroupCache().entries()).filter(([_, u]) => u && u.needsWrite)
            expect(dirtyAfter.length).toBeGreaterThan(0)

            await groupStore.flush()

            // Second flush wrote the updated properties merged onto the still-referenced cache.
            expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
            expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledWith(
                teamId,
                1,
                'test',
                1,
                { test: 'test', a: '1', b: '2' },
                group.created_at,
                {},
                {}
            )
        })
    })

    describe('releaseBatch()', () => {
        it('is a no-op for an unknown batchId', () => {
            expect(() => groupStore.releaseBatch(999)).not.toThrow()
        })

        it('reports dirty entries and referenced batches in flush stats', async () => {
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now(), 0)
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { b: '2' }, DateTime.now(), 1)

            expect(groupStore.getFlushStats()).toEqual({
                dirtyEntryCount: 1,
                referencedBatchCount: 2,
                cacheEntryCount: 1,
            })
        })

        it('removes clean entries from cache after flush and release', async () => {
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now())

            await groupStore.flush()
            expect(groupStore.getGroupCache().getSize()).toBe(1)
            groupStore.releaseBatch(0)

            expect(groupStore.getGroupCache().getSize()).toBe(0)
        })

        it('keeps entries that were re-dirtied during the DB write', async () => {
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now())

            // Re-dirty the entry during the async DB write after the linearization point.
            jest.spyOn(groupRepository, 'updateGroupOptimistically').mockImplementationOnce(() => {
                const entry = groupStore.getGroupCache().get(teamId, 1, 'test')
                if (entry) {
                    entry.needsWrite = true
                }
                return Promise.resolve(2)
            })

            await groupStore.flush()

            expect(groupStore.getGroupCache().getSize()).toBe(1)
            expect(groupStore.getGroupCache().get(teamId, 1, 'test')?.needsWrite).toBe(true)
        })

        it('defers eviction of dirty entries until after flush', async () => {
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now())

            groupStore.releaseBatch(0)
            expect(groupStore.getGroupCache().getSize()).toBe(1)

            await groupStore.flush()

            expect(groupStore.getGroupCache().getSize()).toBe(0)
        })

        it('keeps overlapping batch entries until the last release', async () => {
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now(), 0)
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { b: '2' }, DateTime.now(), 1)

            await groupStore.flush()

            groupStore.releaseBatch(0)
            expect(groupStore.getGroupCache().getSize()).toBe(1)

            groupStore.releaseBatch(1)
            expect(groupStore.getGroupCache().getSize()).toBe(0)
        })
    })

    describe('shutdown()', () => {
        it('succeeds without calling flush when no dirty entries exist', async () => {
            const flushSpy = jest.spyOn(groupStore, 'flush')

            await groupStore.shutdown()

            expect(flushSpy).not.toHaveBeenCalled()
        })

        it('throws when dirty entries exist — caller must flush first', async () => {
            // upsertGroup on an existing group with new properties marks the cache entry dirty
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now())

            expect(() => groupStore.shutdown()).toThrow(/dirty cache entries/)
        })

        it('emits accumulated metrics before throwing on dirty cache', async () => {
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now())

            const emitSpy = jest.spyOn(groupStore as any, 'emitAccumulatedMetrics')

            expect(() => groupStore.shutdown()).toThrow()

            expect(emitSpy).toHaveBeenCalledTimes(1)
        })

        it('explicit flush before shutdown succeeds', async () => {
            await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: '1' }, DateTime.now())

            await groupStore.flush()
            await expect(groupStore.shutdown()).resolves.not.toThrow()
        })
    })
})
