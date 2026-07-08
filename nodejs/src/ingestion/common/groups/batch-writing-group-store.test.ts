// sort-imports-ignore
import { DateTime } from 'luxon'

import { Group, ProjectId, TeamId } from '~/types'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { RaceConditionError } from '~/common/utils/utils'

import { BatchWritingGroupStore } from './batch-writing-group-store'
import { groupCacheOperationsCounter } from './metrics'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { GroupRepository } from '~/common/groups/repositories/group-repository.interface'

// Mock the module before importing
jest.mock('~/ingestion/common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

import { GroupsOutput, IngestionWarningsOutput } from '~/common/outputs'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'

// Mock the DB class

describe('BatchWritingGroupStore', () => {
    let groupRepository: GroupRepository
    let groupStore: BatchWritingGroupStore
    let clickhouseGroupRepository: ClickhouseGroupRepository
    let teamId: TeamId
    let projectId: ProjectId
    let group: Group
    let mockOutputs: IngestionOutputs<GroupsOutput | IngestionWarningsOutput>

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

        clickhouseGroupRepository = {
            upsertGroup: jest.fn().mockResolvedValue(undefined),
        } as unknown as ClickhouseGroupRepository
        mockOutputs = {} as unknown as IngestionOutputs<GroupsOutput | IngestionWarningsOutput>
        groupStore = new BatchWritingGroupStore(mockOutputs, groupRepository, clickhouseGroupRepository)
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

        await groupStore.flush()

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
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(1)
        expect((groupRepository as any).lastTransactionMock.insertGroup).toHaveBeenCalledTimes(1)
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
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(1)
        expect((groupRepository as any).lastTransactionMock.insertGroup).toHaveBeenCalledTimes(1)

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
        jest.spyOn(groupRepository, 'fetchGroup').mockResolvedValue(group)
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'updated' }, DateTime.now())

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(0)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(clickhouseGroupRepository.upsertGroup).toHaveBeenCalledTimes(0)

        await groupStore.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(5)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(1)
        expect((groupRepository as any).lastTransactionMock.updateGroup).toHaveBeenCalledTimes(1)
        expect(clickhouseGroupRepository.upsertGroup).toHaveBeenCalledTimes(1)
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

    it('should capture warning and stop retrying if message size too large', async () => {
        // we need to mock the clickhouse repository upsertGroup method
        clickhouseGroupRepository.upsertGroup = jest
            .fn()
            .mockRejectedValue(new MessageSizeTooLarge('test', new Error('test')))

        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())

        await groupStore.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(0)
        // No transaction calls expected since optimistic update failed
        expect(emitIngestionWarning).toHaveBeenCalledWith(mockOutputs, teamId, {
            type: 'group_upsert_message_size_too_large',
            details: {
                groupTypeIndex: 1,
                groupKey: 'test',
                distinctId: `${teamId}:test`,
            },
            category: 'size',
            severity: 'error',
            pipelineStep: 'group-store',
        })
    })

    it('should retry on race condition error and clear cache', async () => {
        let insertCounter = 0
        let fetchCounter = 0
        jest.spyOn(groupRepository, 'fetchGroup').mockImplementation(() => {
            fetchCounter++
            if (fetchCounter === 1) {
                return Promise.resolve(undefined)
            } else {
                return Promise.resolve(group)
            }
        })

        // Override the transaction mock to throw on first insertGroup call
        groupRepository.inTransaction = jest.fn().mockImplementation(async (description, transaction) => {
            const mockTransaction = {
                fetchGroup: jest.fn().mockImplementation(() => {
                    return Promise.resolve(group)
                }),
                insertGroup: jest.fn().mockImplementation(() => {
                    insertCounter++
                    if (insertCounter === 1) {
                        throw new RaceConditionError('Parallel posthog_group inserts, retry')
                    }
                    return Promise.resolve(1)
                }),
                updateGroup: jest.fn().mockImplementation(() => {
                    return Promise.resolve(1)
                }),
            }
            ;(groupRepository as any).lastTransactionMock = mockTransaction
            return await transaction(mockTransaction)
        })

        // track cache delete
        const groupCache = groupStore.getGroupCache()
        const cacheDeleteSpy = jest.spyOn(groupCache, 'delete')

        // Add to cache to verify it gets cleared on race condition
        await groupStore.upsertGroup(teamId, projectId, 1, 'test', { a: 'test' }, DateTime.now())

        await groupStore.flush()

        expect(groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
        expect(groupRepository.fetchGroup).toHaveBeenCalledTimes(2) // Once for initial fetch, once for retry
        expect(groupRepository.inTransaction).toHaveBeenCalledTimes(1) // Once for initial insert, once for retry (new group)
        expect((groupRepository as any).lastTransactionMock.insertGroup).toHaveBeenCalledTimes(1)

        expect(cacheDeleteSpy).toHaveBeenCalledWith(teamId, 'test')

        // Final call should succeed
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
                const entry = groupStore.getGroupCache().get(teamId, 'test')
                if (entry) {
                    entry.needsWrite = true
                }
                return Promise.resolve(2)
            })

            await groupStore.flush()

            expect(groupStore.getGroupCache().getSize()).toBe(1)
            expect(groupStore.getGroupCache().get(teamId, 'test')?.needsWrite).toBe(true)
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
